"""Acceso a datos: sesiones y operaciones de dominio con auditoría obligatoria."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..cost_engine.engine import input_hash
from ..pipeline import PipelineResult
from ..schemas.cost_master import CostMaster
from ..schemas.manufacturing import ManufacturingJob
from . import models as m


def make_engine(url: Optional[str] = None):
    url = url or settings.database_url
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, **kw)


def make_session_factory(url: Optional[str] = None) -> sessionmaker:
    return sessionmaker(bind=make_engine(url), expire_on_commit=False)


def audit(s: Session, user: str, action: str, project_id: Optional[int] = None, entity: Optional[str] = None,
          old: Any = None, new: Any = None, detail: Optional[str] = None) -> None:
    s.add(m.AuditLog(user=user, project_id=project_id, action=action, entity=entity, old_value=old, new_value=new, detail=detail))


def get_project(s: Session, code: str) -> m.Project:
    p = s.scalar(select(m.Project).where(m.Project.project_code == code, m.Project.deleted_at.is_(None)))
    if p is None:
        raise LookupError(f"proyecto '{code}' no existe")
    return p


def create_project(s: Session, code: str, user: str, **fields: Any) -> m.Project:
    p = m.Project(project_code=code, created_by=user, **fields)
    s.add(p)
    s.flush()
    audit(s, user, "project_created", p.id, "project", new={"project_code": code, **fields})
    return p


def store_document(s: Session, project: m.Project, src: Path, source_type: str, user: str,
                   storage_dir: Optional[Path] = None) -> m.Document:
    """Copia original inmutable en storage/<project>/<sha256>__<filename>. Nunca se modifica."""
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    base = (storage_dir or settings.storage_dir) / project.project_code / "originals"
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"{sha[:16]}__{src.name}"
    if not dest.exists():
        shutil.copyfile(src, dest)
        dest.chmod(0o444)  # sólo lectura
    count = s.scalar(select(func.count()).select_from(m.Document)) or 0
    doc = m.Document(document_code=f"DOC-{count + 1:05d}", project_id=project.id, filename=src.name,
                     checksum_sha256=sha, storage_path=str(dest), source_type=source_type, uploaded_by=user)
    s.add(doc)
    s.flush()
    audit(s, user, "file_uploaded", project.id, "document", new={"filename": src.name, "sha256": sha})
    return doc


def add_interpretation(s: Session, project: m.Project, job: ManufacturingJob, user: str,
                       interpreter: str = "manual", status: str = "valid") -> m.Interpretation:
    last = s.scalar(select(func.max(m.Interpretation.version)).where(m.Interpretation.project_id == project.id)) or 0
    rec = m.Interpretation(project_id=project.id, version=last + 1, interpreter=interpreter, status=status,
                           schema_version=job.schema_version, input_hash=input_hash(job),
                           ai_model=job.interpretation_quality.model, prompt_version=job.interpretation_quality.prompt_version,
                           payload=job.model_dump(mode="json"), created_by=user)
    s.add(rec)
    s.flush()
    for c in job.active_components():
        s.add(m.Component(interpretation_id=rec.id, component_code=c.component_id, description=c.description,
                          make_or_buy=c.make_or_buy.value,
                          material_grade=str(c.material.grade.value) if c.material and c.material.grade.known else None,
                          material_form=str(getattr(c.material.form.value, "value", c.material.form.value)) if c.material and c.material.form.known else None,
                          quantity_per_parent=c.quantity_per_parent.value))
    audit(s, user, "interpretation_saved", project.id, "interpretation", new={"version": rec.version, "interpreter": interpreter})
    return rec


def latest_interpretation(s: Session, project: m.Project) -> m.Interpretation:
    rec = s.scalar(select(m.Interpretation).where(m.Interpretation.project_id == project.id)
                   .order_by(m.Interpretation.version.desc()).limit(1))
    if rec is None:
        raise LookupError(f"proyecto {project.project_code} sin interpretación")
    return rec


def save_cost_master(s: Session, master: CostMaster, report: dict, user: str, activate: bool = True) -> m.CostMasterVersion:
    existing = s.scalar(select(m.CostMasterVersion).where(m.CostMasterVersion.version == master.version))
    if existing is None:
        existing = m.CostMasterVersion(version=master.version, source_filename=master.source_filename, is_sample=master.is_sample,
                                       import_report=report, payload=json.loads(master.model_dump_json()), imported_by=user)
        s.add(existing)
    if activate:
        for cm in s.scalars(select(m.CostMasterVersion).where(m.CostMasterVersion.active.is_(True))):
            cm.active = False
        existing.active = True
    s.flush()
    audit(s, user, "cost_master_imported", None, "cost_master", new={"version": master.version, "is_sample": master.is_sample})
    return existing


def active_cost_master(s: Session) -> CostMaster:
    rec = s.scalar(select(m.CostMasterVersion).where(m.CostMasterVersion.active.is_(True)))
    if rec is None:
        raise LookupError("no hay Cost Master activo: importar COST_MASTER.xlsx")
    return CostMaster.model_validate(rec.payload)


def save_results(s: Session, project: m.Project, interp: m.Interpretation, res: PipelineResult, user: str) -> m.CostResultRecord:
    last = s.scalar(select(func.max(m.CostResultRecord.costing_version)).where(m.CostResultRecord.project_id == project.id)) or 0
    cost = res.cost.model_copy(update={"costing_version": last + 1})
    cr = m.CostResultRecord(project_id=project.id, interpretation_id=interp.id, costing_version=last + 1,
                            engine_version=cost.engine_version, rule_set_ref=cost.rule_set_ref,
                            cost_master_version=cost.cost_master_version, as_of_date=cost.as_of_date, currency=cost.currency,
                            is_partial=cost.is_partial, uses_sample_data=cost.uses_sample_data,
                            payload={"costing": cost.model_dump(mode="json"), "quote": res.quote.model_dump(mode="json"),
                                     "audit": res.audit()})
    s.add(cr)
    s.flush()
    s.add(m.RiskResultRecord(cost_result_id=cr.id, risk_model_version=res.risk.risk_model_version,
                             overall_risk=res.risk.overall_risk, cei=float(res.risk.cei), payload=res.risk.model_dump(mode="json")))
    audit(s, user, "cost_recalculated", project.id, "cost_result",
          new={"costing_version": cr.costing_version, "status": res.quote.status, "rounded_price": str(res.quote.rounded_price)})
    audit(s, user, "risk_recalculated", project.id, "risk_result", new={"overall": res.risk.overall_risk, "cei": str(res.risk.cei)})
    return cr

"""API local (FastAPI). Monolito modular: la UI (fase 7) consume estos endpoints.

uvicorn ts_quoter.api.main:app --reload
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ENGINE_VERSION, SCHEMA_VERSION
from ..config import settings
from ..db import models as m
from ..db import repository as repo
from ..importers.excel import import_cost_master
from ..logging_setup import setup_logging
from ..pipeline import run
from ..rules.loader import load_rules
from ..schemas.manufacturing import ManufacturingJob
from ..schemas.overrides import OverrideError, apply_override

setup_logging()
app = FastAPI(title="T&S Cotizador", version=ENGINE_VERSION,
              description="Estimación auditable de fabricación especial en acero inoxidable. Uso interno.")
_SessionFactory = repo.make_session_factory()


def get_session():
    s = _SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _error(module: str, what: str, lost: bool, action: str, status: int = 400, detail: Any = None) -> HTTPException:
    """Errores útiles (sec. 127): qué falló, en qué módulo, si se perdió información, qué hacer."""
    return HTTPException(status_code=status, detail={"module": module, "error": what, "data_lost": lost,
                                                     "user_action": action, "detail": detail})


class ProjectIn(BaseModel):
    project_code: str
    customer: Optional[str] = None
    description: Optional[str] = None
    drawing_number: Optional[str] = None
    product_family: Optional[str] = None
    user: str = "estimator"


class OverrideIn(BaseModel):
    field_path: str
    new_value: Any
    unit: Optional[str] = None
    reason: Optional[str] = None
    user: str


class TextInterpretIn(BaseModel):
    text: str
    user: str = "estimator"
    quantity: Optional[int] = None
    currency: Optional[str] = None
    customer: Optional[str] = None
    export: Optional[bool] = None


class CalcIn(BaseModel):
    as_of: Optional[date] = None
    user: str = "estimator"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": ENGINE_VERSION, "schema": SCHEMA_VERSION, "env": settings.environment,
            "ai_provider": settings.ai_provider}


@app.post("/projects")
def create_project(body: ProjectIn, s: Session = Depends(get_session)) -> dict:
    if s.scalar(select(m.Project).where(m.Project.project_code == body.project_code)):
        raise _error("projects", f"proyecto '{body.project_code}' ya existe", False, "Usar otro código", 409)
    p = repo.create_project(s, body.project_code, body.user, customer=body.customer, description=body.description,
                            drawing_number=body.drawing_number, product_family=body.product_family)
    return {"project_code": p.project_code, "id": p.id, "status": p.status}


@app.get("/projects")
def list_projects(s: Session = Depends(get_session)) -> list[dict]:
    rows = s.scalars(select(m.Project).where(m.Project.deleted_at.is_(None)).order_by(m.Project.created_at.desc()))
    return [{"project_code": p.project_code, "customer": p.customer, "status": p.status, "created_at": p.created_at} for p in rows]


@app.post("/projects/{code}/documents")
def upload_document(code: str, source_type: str = Form(...), user: str = Form("estimator"),
                    file: UploadFile = File(...), s: Session = Depends(get_session)) -> dict:
    p = _project(s, code)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / Path(file.filename or "upload.bin").name
        with tmp.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        doc = repo.store_document(s, p, tmp, source_type, user)
    return {"document_code": doc.document_code, "sha256": doc.checksum_sha256, "stored_as": doc.storage_path}


@app.post("/projects/{code}/interpretations")
def save_interpretation(code: str, payload: dict, user: str = "estimator", s: Session = Depends(get_session)) -> dict:
    """Captura manual del MCJ (demo 1). Valida contra el esquema antes de guardar."""
    p = _project(s, code)
    try:
        job = ManufacturingJob.model_validate(payload)
    except ValidationError as e:
        raise _error("schemas", "Manufacturing JSON inválido", False, "Corregir los campos indicados",
                     422, [{"loc": x["loc"], "msg": x["msg"]} for x in e.errors()[:20]])
    rec = repo.add_interpretation(s, p, job, user)
    return {"version": rec.version, "input_hash": rec.input_hash}


@app.post("/projects/{code}/overrides")
def override(code: str, body: OverrideIn, s: Session = Depends(get_session)) -> dict:
    p = _project(s, code)
    interp = repo.latest_interpretation(s, p)
    job = ManufacturingJob.model_validate(interp.payload)
    try:
        new = apply_override(job, body.field_path, body.new_value, body.user, datetime.now(timezone.utc), body.reason, body.unit)
    except (OverrideError, AttributeError, IndexError, ValidationError) as e:
        raise _error("overrides", f"no se pudo aplicar override en '{body.field_path}': {e}", False, "Verificar la ruta del campo y el tipo de valor")
    rec = repo.add_interpretation(s, p, new, body.user, interpreter=interp.interpreter)
    repo.audit(s, body.user, "value_changed", p.id, body.field_path, old=new.audit.overrides[-1].original_value,
               new=new.audit.overrides[-1].new_value, detail=body.reason)
    return {"version": rec.version}


@app.post("/projects/{code}/calculate")
def calculate(code: str, body: CalcIn, s: Session = Depends(get_session)) -> dict:
    """Recalcula sin IA (sec. 125). Guarda una nueva versión de costeo (inmutable)."""
    p = _project(s, code)
    interp = repo.latest_interpretation(s, p)
    try:
        master = repo.active_cost_master(s)
    except LookupError as e:
        raise _error("cost_master", str(e), False, "Importar COST_MASTER.xlsx en /cost-master/import", 409)
    rules = load_rules()
    job = ManufacturingJob.model_validate(interp.payload)
    res = run(job, master, rules, body.as_of or date.today())
    rec = repo.save_results(s, p, interp, res, body.user)
    p.status = "requires_review" if res.cost.review_items else "ready_for_approval"
    return {"costing_version": rec.costing_version, "quote": res.quote.model_dump(mode="json"),
            "risk": {"overall": res.risk.overall_risk, "score": str(res.risk.overall_score), "cei": str(res.risk.cei),
                     "classification": res.risk.cei_classification},
            "requires_review": [r.model_dump(mode="json") for r in res.cost.review_items],
            "coverage": res.cost.coverage.model_dump(mode="json")}


@app.get("/projects/{code}/results/{version}")
def get_result(code: str, version: int, s: Session = Depends(get_session)) -> dict:
    p = _project(s, code)
    rec = s.scalar(select(m.CostResultRecord).where(m.CostResultRecord.project_id == p.id, m.CostResultRecord.costing_version == version))
    if rec is None:
        raise _error("results", f"versión {version} no existe", False, "Consultar versiones disponibles", 404)
    return rec.payload


@app.get("/projects/{code}/results/{version}/explain/{line_id}")
def explain_line(code: str, version: int, line_id: str, s: Session = Depends(get_session)) -> dict:
    """'Explain calculation' (sec. 97): fórmula + insumos + fuentes + reglas de una línea."""
    data = get_result(code, version, s)
    line = next((l for l in data["costing"]["lines"] if l["line_id"] == line_id), None)
    if line is None:
        raise _error("results", f"línea {line_id} no existe", False, "Verificar line_id", 404)
    return line


@app.post("/cost-master/import")
def import_master(file: UploadFile = File(...), user: str = Form("admin"), s: Session = Depends(get_session)) -> JSONResponse:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / Path(file.filename or "COST_MASTER.xlsx").name
        with tmp.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        master, rep = import_cost_master(tmp, load_rules())
    if master is None:
        return JSONResponse(status_code=422, content={"module": "importers", "error": "Cost Master inválido", "data_lost": False,
                                                      "user_action": "Corregir el archivo según el reporte", "report": rep.as_dict()})
    if master.is_sample and not settings.allow_sample_data:
        raise _error("importers", "SAMPLE DATA no permitido en este entorno", False, "Usar datos de producción", 409)
    repo.save_cost_master(s, master, rep.as_dict(), user)
    return JSONResponse(content={"version": master.version, "is_sample": master.is_sample, "report": rep.as_dict()})


@app.get("/projects/{code}/audit")
def project_audit(code: str, s: Session = Depends(get_session)) -> list[dict]:
    p = _project(s, code)
    rows = s.scalars(select(m.AuditLog).where(m.AuditLog.project_id == p.id).order_by(m.AuditLog.timestamp))
    return [{"timestamp": r.timestamp, "user": r.user, "action": r.action, "entity": r.entity,
             "old_value": r.old_value, "new_value": r.new_value, "detail": r.detail} for r in rows]


def _project(s: Session, code: str) -> m.Project:
    try:
        return repo.get_project(s, code)
    except LookupError as e:
        raise _error("projects", str(e), False, "Verificar código de proyecto", 404)


@app.post("/projects/{code}/interpret/text")
def interpret_text(code: str, body: TextInterpretIn, s: Session = Depends(get_session)) -> dict:
    """Interpreter 1 (texto). Guarda una nueva versión de interpretación; si la IA falla, el proyecto queda intacto."""
    from ..interpreters.base import InterpreterInput
    from ..interpreters.payload import human_project_value
    from ..interpreters.text.interpreter import TextInterpreter
    from ..providers.anthropic import get_provider
    from ..schemas.manufacturing import Project as ProjectModel

    p = _project(s, code)
    pdata: dict = {"project_id": p.project_code, "created_by": body.user, "description": p.description,
                   "product_family": p.product_family}
    for k, v in (("quantity", body.quantity), ("currency", body.currency.upper() if body.currency else None),
                 ("customer", body.customer or p.customer), ("export", body.export)):
        if v is not None:
            pdata[k] = human_project_value(v)
    interp = TextInterpreter(get_provider())
    run_ = interp.interpret(InterpreterInput(project=ProjectModel(**pdata), text=body.text))
    repo.audit(s, body.user, "interpretation_executed", p.id, "text_interpreter",
               new={"outcome": run_.outcome, "model": run_.model, "prompt_version": run_.prompt_version,
                    "input_hash": run_.input_hash, "output_hash": run_.output_hash, "guards": interp.guard_log},
               detail="; ".join(run_.errors) or None)
    if run_.job is None:
        s.commit()  # la bitácora de la falla se conserva
        raise _error("interpreters.text", "La interpretación falló", False,
                     "Reintentar, revisar configuración IA (.env) o capturar el MCJ manualmente", 502, run_.errors)
    rec = repo.add_interpretation(s, p, run_.job, body.user, interpreter="text", status=run_.outcome)
    p.status = "requires_review"
    return {"version": rec.version, "outcome": run_.outcome, "guards": interp.guard_log,
            "interpreted": run_.job.model_dump(mode="json"),
            "review_items": [r.model_dump(mode="json") for r in run_.job.review_items]}

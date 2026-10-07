"""Modelo de base de datos (SQLAlchemy 2.0). SQLite en MVP, PostgreSQL después (sin SQL específico de motor).

Principios:
  * interpretaciones, resultados y reglas son INMUTABLES y versionados (nueva fila, nunca UPDATE del contenido)
  * soft delete (deleted_at) en entidades editables
  * los blobs JSON guardan el MCJ / resultados completos; las columnas indexan lo consultable
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SoftDelete:
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base, SoftDelete):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="estimator")  # admin | estimator | reviewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base, SoftDelete):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_code: Mapped[str] = mapped_column(String(50), unique=True)
    internal_reference: Mapped[Optional[str]] = mapped_column(String(100))
    customer: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    customer_part_number: Mapped[Optional[str]] = mapped_column(String(100))
    drawing_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    product_family: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revisions: Mapped[list["ProjectRevision"]] = relationship(back_populates="project")


class ProjectRevision(Base):
    """Revisión de dibujo: cada REV tiene su propio BOM/interpretaciones (sec. 73, 155)."""

    __tablename__ = "project_revisions"
    __table_args__ = (UniqueConstraint("project_id", "drawing_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    drawing_revision: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project: Mapped[Project] = relationship(back_populates="revisions")


class Document(Base, SoftDelete):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_code: Mapped[str] = mapped_column(String(50), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))  # copia original inmutable
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    revision: Mapped[Optional[str]] = mapped_column(String(20))
    source_type: Mapped[str] = mapped_column(String(30))
    sent_to_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(80))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Interpretation(Base):
    """MCJ versionado. Nunca se edita: cada corrección = nueva versión."""

    __tablename__ = "interpretations"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    revision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("project_revisions.id"))
    version: Mapped[int] = mapped_column(Integer)
    interpreter: Mapped[str] = mapped_column(String(20))  # manual | text | drawing | hybrid
    status: Mapped[str] = mapped_column(String(30))  # valid | partial | failed_interpretation
    schema_version: Mapped[str] = mapped_column(String(20))
    input_hash: Mapped[str] = mapped_column(String(64))
    ai_model: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    review_state: Mapped[str] = mapped_column(String(20), default="not_reviewed")  # not_reviewed|reviewed|approved
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(80))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Component(Base):
    """Proyección consultable de componentes (para similitud / reportes). Fuente de verdad: payload."""

    __tablename__ = "components"
    id: Mapped[int] = mapped_column(primary_key=True)
    interpretation_id: Mapped[int] = mapped_column(ForeignKey("interpretations.id"), index=True)
    component_code: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    make_or_buy: Mapped[str] = mapped_column(String(10))
    material_grade: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    material_form: Mapped[Optional[str]] = mapped_column(String(30))
    quantity_per_parent: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))


class MaterialRecord(Base):
    """Catálogo de materiales normalizados con alias (raw -> normalized)."""

    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    grade: Mapped[str] = mapped_column(String(30), unique=True)
    standard: Mapped[Optional[str]] = mapped_column(String(50))
    density_kg_m3: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    aliases: Mapped[list] = mapped_column(JSON, default=list)


class ProcessRecord(Base):
    __tablename__ = "processes"
    id: Mapped[int] = mapped_column(primary_key=True)
    process_type: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class CostMasterVersion(Base):
    """Cost Master importado (inmutable). cost_sources referencia esta versión."""

    __tablename__ = "cost_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(300))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    import_report: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict] = mapped_column(JSON)
    imported_by: Mapped[Optional[str]] = mapped_column(String(80))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class CostResultRecord(Base):
    __tablename__ = "cost_results"
    __table_args__ = (UniqueConstraint("project_id", "costing_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    interpretation_id: Mapped[int] = mapped_column(ForeignKey("interpretations.id"))
    costing_version: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(40))
    rule_set_ref: Mapped[str] = mapped_column(String(80))
    cost_master_version: Mapped[str] = mapped_column(String(40))
    as_of_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    is_partial: Mapped[bool] = mapped_column(Boolean)
    uses_sample_data: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskResultRecord(Base):
    __tablename__ = "risk_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    cost_result_id: Mapped[int] = mapped_column(ForeignKey("cost_results.id"), unique=True)
    risk_model_version: Mapped[str] = mapped_column(String(40))
    overall_risk: Mapped[str] = mapped_column(String(20))
    cei: Mapped[float] = mapped_column(Numeric(6, 2))
    payload: Mapped[dict] = mapped_column(JSON)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)  # p.ej. "default"
    description: Mapped[Optional[str]] = mapped_column(Text)


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"))
    version: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Supplier(Base, SoftDelete):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name_raw: Mapped[str] = mapped_column(String(200))
    name_normalized: Mapped[str] = mapped_column(String(200), index=True)
    possible_duplicate_of: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"))


class PurchaseHistory(Base):
    __tablename__ = "purchase_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[str] = mapped_column(String(50), index=True)
    date: Mapped[date] = mapped_column(Date)
    supplier_raw: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    material_grade_raw: Mapped[Optional[str]] = mapped_column(String(50))
    material_grade: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    material_form: Mapped[Optional[str]] = mapped_column(String(30))
    quantity: Mapped[float] = mapped_column(Numeric(14, 4))
    unit: Mapped[str] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(3))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 4))
    purchase_order: Mapped[Optional[str]] = mapped_column(String(50))
    possible_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    possible_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    import_checksum: Mapped[str] = mapped_column(String(64))


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    cost_result_id: Mapped[int] = mapped_column(ForeignKey("cost_results.id"))
    status: Mapped[str] = mapped_column(String(30))
    calculated_price: Mapped[float] = mapped_column(Numeric(16, 2))
    rounded_price: Mapped[float] = mapped_column(Numeric(16, 2))
    approved_price: Mapped[Optional[float]] = mapped_column(Numeric(16, 2))
    approved_by: Mapped[Optional[str]] = mapped_column(String(80))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    validity_days: Mapped[int] = mapped_column(Integer, default=15)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActualCost(Base):
    """Learning loop: estimado vs real (fase 10). Nunca ajusta tarifas automáticamente."""

    __tablename__ = "actual_costs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    cost_result_id: Mapped[int] = mapped_column(ForeignKey("cost_results.id"))
    metric: Mapped[str] = mapped_column(String(50))  # material_qty, welding_hours, total_cost, margin ...
    estimated_value: Mapped[float] = mapped_column(Numeric(16, 4))
    actual_value: Mapped[float] = mapped_column(Numeric(16, 4))
    unit: Mapped[str] = mapped_column(String(10))
    recorded_by: Mapped[Optional[str]] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user: Mapped[str] = mapped_column(String(80))
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), index=True)
    action: Mapped[str] = mapped_column(String(50))  # file_uploaded, interpretation_executed, value_changed, ...
    entity: Mapped[Optional[str]] = mapped_column(String(80))
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    detail: Mapped[Optional[str]] = mapped_column(Text)

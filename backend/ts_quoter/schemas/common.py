"""Tipos base compartidos: valores rastreables (hecho vs inferencia), referencias de fuente, revisión."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class StrictModel(BaseModel):
    """Modelo base: rechaza campos no definidos (protege contra campos alucinados por IA)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class SourceStatus(str, Enum):
    EXPLICIT = "explicit"          # el documento lo especifica directamente
    INFERRED = "inferred"          # la IA lo dedujo
    DERIVED = "derived"            # resultado de una fórmula
    DEFAULTED = "defaulted"        # aplicado por una regla interna (versión de regla registrada)
    UNKNOWN = "unknown"            # no hay información suficiente
    CONFLICTING = "conflicting"    # dos fuentes se contradicen
    USER_CONFIRMED = "user_confirmed"  # un humano lo validó


#: estados que se consideran "dato confiable" para el cálculo
TRUSTED_STATUSES = {SourceStatus.EXPLICIT, SourceStatus.DERIVED, SourceStatus.USER_CONFIRMED}
#: estados en que el valor NO debe existir
VALUELESS_STATUSES = {SourceStatus.UNKNOWN}


class SourceRef(StrictModel):
    """De dónde salió un dato: documento + página + región (+ extracto)."""

    document_id: Optional[str] = None
    page: Optional[int] = None
    region: Optional[str] = None  # p.ej. "title_block", "NOTE 4", "DETAIL B", bbox "x,y,w,h"
    excerpt: Optional[str] = None
    rule_ref: Optional[str] = None  # si source_status = defaulted: id de la regla + versión
    note: Optional[str] = None


class Tracked(BaseModel, Generic[T]):
    """Valor con procedencia. Todo campo crítico del Manufacturing Cost JSON usa este envoltorio.

    Invariantes:
      * unknown  -> value es None
      * cualquier otro estado distinto de conflicting -> value no es None
      * defaulted -> source_reference.rule_ref obligatorio (trazabilidad de la regla)
    """

    model_config = ConfigDict(extra="forbid")

    value: Optional[T] = None
    unit: Optional[str] = None
    source_status: SourceStatus = SourceStatus.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_reference: Optional[SourceRef] = None
    raw_value: Optional[str] = None  # texto original, nunca se destruye

    @model_validator(mode="after")
    def _check_invariants(self) -> "Tracked[T]":
        st = self.source_status
        if st == SourceStatus.UNKNOWN and self.value is not None:
            raise ValueError("source_status=unknown no puede llevar value (Regla 3: unknown permanece unknown)")
        if st not in (SourceStatus.UNKNOWN, SourceStatus.CONFLICTING) and self.value is None:
            raise ValueError(f"source_status={st.value} requiere value")
        if st == SourceStatus.DEFAULTED and (self.source_reference is None or not self.source_reference.rule_ref):
            raise ValueError("source_status=defaulted requiere source_reference.rule_ref")
        return self

    @property
    def known(self) -> bool:
        return self.value is not None and self.source_status != SourceStatus.CONFLICTING

    def num(self) -> Optional[Decimal]:
        """Valor numérico como Decimal (determinístico) o None si no se conoce."""
        if not self.known:
            return None
        return Decimal(str(self.value))


def explicit(value: Any, unit: str | None = None, confidence: float = 1.0, **ref: Any) -> dict:
    """Atajo para construir dicts de Tracked explícitos (útil en tests y entrada manual)."""
    d: dict[str, Any] = {"value": value, "source_status": "explicit", "confidence": confidence}
    if unit:
        d["unit"] = unit
    if ref:
        d["source_reference"] = ref
    return d


def unknown(unit: str | None = None) -> dict:
    d: dict[str, Any] = {"value": None, "source_status": "unknown", "confidence": 0.0}
    if unit:
        d["unit"] = unit
    return d


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3, Severity.INFO: 4}


class Impact(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewItem(StrictModel):
    """Alerta de revisión por excepción (sección REQUIRES REVIEW)."""

    review_id: str
    severity: Severity
    category: str
    description: str
    cost_impact: Impact
    recommended_action: str
    field_path: Optional[str] = None
    question: Optional[str] = None  # pregunta técnica concreta para el cliente (sec. 163)


class RequirementStatus(str, Enum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"
    INFERRED = "inferred"

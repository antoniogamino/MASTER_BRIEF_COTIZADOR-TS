"""Contexto de cálculo: acumula líneas de costo, alertas y traza. Sin estado global, sin reloj."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from ..units import UnitError, convert
from ..money import FxConversion, MissingFxError, convert_money
from ..rules.loader import RuleSet
from ..schemas.common import Impact, ReviewItem, Severity, Tracked
from ..schemas.cost_master import CostMaster
from ..schemas.manufacturing import ManufacturingJob
from ..schemas.results import CostLine, CostSourceRef, LineStatus, TraceInput

ZERO = Decimal("0")


@dataclass
class CostContext:
    job: ManufacturingJob
    master: CostMaster
    rules: RuleSet
    as_of: date
    currency: str
    lines: list[CostLine] = field(default_factory=list)
    reviews: list[ReviewItem] = field(default_factory=list)
    _seq: int = 0
    _rseq: int = 0

    # ------------------------------------------------------------------ trace helpers
    def ti(self, tracked: Tracked, path: str) -> TraceInput:
        """Insumo de fórmula a partir de un campo rastreable del MCJ."""
        val = None if tracked.value is None else str(getattr(tracked.value, "value", tracked.value))
        src = f"mcj:{path} ({tracked.source_status.value}, conf={tracked.confidence:.2f})"
        if tracked.source_reference and (tracked.source_reference.page or tracked.source_reference.region):
            sr = tracked.source_reference
            src += f" @doc={sr.document_id} p={sr.page} {sr.region or ''}".rstrip()
        if tracked.source_reference and tracked.source_reference.rule_ref:
            src += f" rule={tracked.source_reference.rule_ref}"
        return TraceInput(value=val, unit=tracked.unit, source=src)

    def rule_input(self, path: str, value: Any, unit: Optional[str] = None, key: Optional[str] = None) -> TraceInput:
        ref = self.rules.rule_ref(path if key is None else f"{path}[{key}]")
        return TraceInput(value=str(value), unit=unit, source=ref)

    def derived(self, value: Any, unit: Optional[str], formula: str) -> TraceInput:
        return TraceInput(value=str(value), unit=unit, source=f"derived: {formula}")

    def val(self, tracked: Tracked, unit: Optional[str] = None) -> Optional[Decimal]:
        """Valor numérico convertido a ``unit`` (nunca mezcla unidades en silencio). None si desconocido."""
        n = tracked.num()
        if n is None or unit is None:
            return n
        if tracked.unit is None:
            raise UnitError(f"valor {tracked.value} sin unidad; se esperaba {unit}")
        if tracked.unit == unit:
            return n
        return convert(n, tracked.unit, unit)

    # ------------------------------------------------------------------ money
    def to_project(self, amount: Decimal, ccy: str) -> tuple[Decimal, FxConversion]:
        fx = convert_money(amount, ccy, self.currency, self.master, self.rules)
        return fx.converted_value, fx

    # ------------------------------------------------------------------ lines
    def next_id(self, prefix: str = "L") -> str:
        self._seq += 1
        return f"{prefix}{self._seq:04d}"

    def add(self, **kw: Any) -> CostLine:
        line = CostLine(line_id=self.next_id(), status=kw.pop("status", LineStatus.COMPLETE), **kw)
        self.lines.append(line)
        return line

    def missing(self, *, category: str, description: str, reason: str, component_id: Optional[str] = None,
                process_id: Optional[str] = None, formula: str = "n/a", inputs: Optional[dict] = None,
                severity: Severity = Severity.HIGH, impact: Impact = Impact.HIGH, field_path: Optional[str] = None,
                question: Optional[str] = None, action: Optional[str] = None) -> CostLine:
        line = self.add(category=category, description=description, status=LineStatus.MISSING,
                        component_id=component_id, process_id=process_id, formula=formula,
                        inputs=inputs or {}, missing_reason=reason)
        self.review(severity=severity, category=category, description=f"{description}: {reason}",
                    impact=impact, action=action or "Completar el dato o capturar una suposición aprobada",
                    field_path=field_path, question=question)
        return line

    def review(self, *, severity: Severity, category: str, description: str, impact: Impact, action: str,
               field_path: Optional[str] = None, question: Optional[str] = None) -> None:
        # deduplicar por (field_path, description)
        for r in self.reviews:
            if r.field_path == field_path and r.description == description:
                return
        self._rseq += 1
        self.reviews.append(ReviewItem(review_id=f"R{self._rseq:04d}", severity=severity, category=category,
                                       description=description, cost_impact=impact, recommended_action=action,
                                       field_path=field_path, question=question))

    # ------------------------------------------------------------------ fx source helper
    @staticmethod
    def fx_source(fx: FxConversion) -> Optional[CostSourceRef]:
        if fx.fx_source == "identity":
            return None
        return CostSourceRef(kind="fx", key=f"{fx.original_currency}->{fx.policy}", original_value=str(fx.original_value),
                             original_currency=fx.original_currency, fx_rate=str(fx.fx_rate), fx_source=fx.fx_source,
                             fx_date=fx.fx_date, converted_value=str(fx.converted_value))


__all__ = ["CostContext", "MissingFxError", "ZERO"]

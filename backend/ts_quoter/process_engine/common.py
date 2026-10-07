"""Utilidades comunes de procesos: horas × tarifa con traza, factores con política para desconocidos."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from ..cost_engine.context import CostContext, MissingFxError
from ..schemas.common import Impact, Severity, Tracked
from ..schemas.manufacturing import Component
from ..schemas.results import CostLine, CostSourceRef, TraceInput

ZERO = Decimal("0")
ONE = Decimal("1")


def enum_val(v: Any) -> Any:
    return getattr(v, "value", v)


def factor(ctx: CostContext, tracked: Tracked, rule_path: str, field_path: str, inputs: dict, name: str,
           category: str, label: str, unknown_sink: Optional[list] = None) -> Decimal:
    """Factor multiplicador desde tabla de reglas.

    Si el dato es desconocido: factor = 1.0 (NO se asume un valor) y se genera alerta indicando que
    el factor no fue aplicado. Así lo desconocido permanece visible.
    """
    if not tracked.known:
        inputs[name] = TraceInput(value="1", unit="factor", source=f"NOT APPLIED: {field_path} unknown")
        if unknown_sink is not None:
            unknown_sink.append(label)
            return ONE
        ctx.review(severity=Severity.MEDIUM, category=category, impact=Impact.MEDIUM, field_path=field_path,
                   description=f"{label} desconocido: factor no aplicado (costo puede estar subestimado)",
                   action=f"Confirmar {label}")
        return ONE
    key = str(enum_val(tracked.value)).lower() if isinstance(tracked.value, bool) else str(enum_val(tracked.value))
    f = ctx.rules.lookup(rule_path, key, None)
    if f is None:
        inputs[name] = TraceInput(value="1", unit="factor", source=f"NOT APPLIED: sin regla {rule_path}[{key}]")
        ctx.review(severity=Severity.LOW, category=category, impact=Impact.LOW, field_path=field_path,
                   description=f"Sin factor en reglas para {label}='{key}'", action="Agregar regla")
        return ONE
    inputs[name] = TraceInput(value=str(f), unit="factor", source=f"{ctx.rules.rule_ref(rule_path)}[{key}] ← {field_path}={key} ({tracked.source_status.value})")
    return Decimal(f)


def tightest_tolerance(comp: Component, ctx: CostContext) -> Optional[Decimal]:
    vals = [ctx.val(t.value, "mm") for t in comp.tolerances if t.value.known]
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def max_dim(comp: Component, ctx: CostContext) -> Optional[Decimal]:
    bb = comp.geometry.bounding_box
    vals = [ctx.val(t, "mm") for t in (bb.length, bb.width, bb.height) if t.known]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def apply_time_overrides(ctx: CostContext, proc: Any, path: str, h_one: Decimal, h_unit: Decimal,
                         inputs: dict, notes: list[str]) -> tuple[Decimal, Decimal]:
    if proc.setup_time_override.known:
        h_one = ctx.val(proc.setup_time_override, "hr")
        inputs["setup_override"] = ctx.ti(proc.setup_time_override, f"{path}.setup_time_override")
        notes.append("setup_time sustituido por override capturado")
    if proc.run_time_override.known:
        h_unit = ctx.val(proc.run_time_override, "hr")
        inputs["run_override"] = ctx.ti(proc.run_time_override, f"{path}.run_time_override")
        notes.append("run_time sustituido por override capturado")
    return h_one, h_unit


def priced_hours(ctx: CostContext, *, rate_key: str, category: str, comp: Component, process_id: Optional[str],
                 path: str, h_one: Decimal, h_unit_piece: Decimal, mult: Decimal, formula: str, inputs: dict,
                 rule_refs: list[str], description: str, notes: Optional[list[str]] = None,
                 quantities: Optional[dict] = None) -> Optional[CostLine]:
    """Costo = horas × tarifa. h_unit_piece es por pieza del componente; se multiplica por ``mult``."""
    rate = ctx.master.rate(rate_key)
    if rate is None:
        ctx.missing(category=category, description=description, reason=f"tarifa '{rate_key}' no existe en Cost Master",
                    component_id=comp.component_id, process_id=process_id, inputs=inputs, formula=formula,
                    severity=Severity.HIGH, action=f"Cargar tarifa '{rate_key}' en COST_MASTER > Processes")
        return None
    try:
        hourly, fx = ctx.to_project(rate.hourly_rate, rate.currency)
    except MissingFxError as e:
        ctx.missing(category=category, description=description, reason=str(e), component_id=comp.component_id,
                    process_id=process_id, severity=Severity.CRITICAL)
        return None
    inputs["hourly_rate"] = TraceInput(value=str(hourly), unit=f"{ctx.currency}/hr",
                                       source=f"cost_master:process_rates[{rate_key}]{' (ESTIMADA)' if rate.estimated else ''}")
    inputs["component_multiplier"] = ctx.derived(mult, "pcs/unit", "Π quantity_per_parent")
    srcs = [CostSourceRef(kind="process_rate", key=rate_key, original_value=str(rate.hourly_rate),
                          original_currency=rate.currency, price_date=rate.effective_date, is_sample=rate.is_sample)]
    if (s := ctx.fx_source(fx)):
        srcs.append(s)
    q = {"setup_hr": str(h_one), "run_hr_per_piece": str(h_unit_piece)}
    if quantities:
        q.update(quantities)
    return ctx.add(category=category, component_id=comp.component_id, process_id=process_id, description=description,
                   one_time=h_one * hourly, per_unit=h_unit_piece * mult * hourly,
                   hours_one_time=h_one, hours_per_unit=h_unit_piece * mult, quantities=q,
                   formula=formula + "  →  cost = setup_hr × rate + run_hr × multiplier × rate",
                   inputs=inputs, sources=srcs, rule_refs=rule_refs, notes=notes or [])

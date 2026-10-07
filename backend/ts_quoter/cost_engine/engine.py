"""Cost Engine determinístico.

    calculate(job, master, rules, as_of) -> CostResult

Mismo input + mismas reglas + mismo Cost Master + misma fecha de cálculo => mismo resultado, bit a bit.
No llama IA. No lee el reloj (``as_of`` es parámetro explícito). No muta el job recibido.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from .. import ENGINE_VERSION, SCHEMA_VERSION
from ..material_engine.material import cost_material
from ..packaging_engine.packaging import cost_buy, cost_engineering, cost_logistics, cost_packaging, cost_quality
from ..process_engine.finishing import cost_surface_polishing, cost_weld_finishing
from ..process_engine.forming import cost_bending, cost_laser, cost_rolling
from ..process_engine.machining import cost_generic, cost_machining, cost_outsourcing
from ..process_engine.welding import cost_welding
from ..money import convert_money
from ..rules.loader import RuleSet
from ..schemas.common import SEVERITY_ORDER, Impact, Severity, SourceStatus
from ..schemas.cost_master import CostMaster
from ..schemas.walk import iter_tracked
from ..schemas.manufacturing import Component, MakeOrBuy, ManufacturingJob
from ..schemas.results import CostLine, CostResult, Coverage, LineStatus
from .context import CostContext

ZERO = Decimal("0")
HUNDRED = Decimal("100")

_DISPATCH = {
    "laser_cutting": cost_laser,
    "bending": cost_bending,
    "rolling": cost_rolling,
    "welding": cost_welding,
    "surface_polishing": cost_surface_polishing,
    "weld_finishing": cost_weld_finishing,
    "machining": cost_machining,
    "outsourcing": cost_outsourcing,
}


def input_hash(job: ManufacturingJob) -> str:
    payload = job.model_dump(mode="json", exclude={"audit"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def component_multipliers(ctx: CostContext) -> dict[str, Optional[Decimal]]:
    """Cantidad de cada componente por UNA unidad de producto cotizado (roll-up de ensamble)."""
    comps = {c.component_id: c for c in ctx.job.active_components()}
    memo: dict[str, Optional[Decimal]] = {}

    def mult(cid: str) -> Optional[Decimal]:
        if cid in memo:
            return memo[cid]
        c = comps[cid]
        own = ctx.val(c.quantity_per_parent) if c.quantity_per_parent.known else None
        parent = mult(c.parent_component_id) if c.parent_component_id in comps else Decimal("1")
        memo[cid] = None if own is None or parent is None else own * parent
        return memo[cid]

    for cid in comps:
        mult(cid)
    return memo


def _epistemic_reviews(ctx: CostContext) -> None:
    job = ctx.job
    for c in job.conflicts:
        if not c.resolved:
            ctx.review(severity=Severity.CRITICAL if "material" in c.field_path else Severity.HIGH, category="conflict",
                       impact=Impact.HIGH, field_path=c.field_path, description=f"Conflicto: {c.description}",
                       action="Resolver conflicto (no se reemplaza silenciosamente)",
                       question=f"Confirmar cuál aplica para {c.field_path}: " + " vs ".join(str(v.get('value')) for v in c.values))
    for u in job.uncertainties:
        ctx.review(severity=Severity.MEDIUM, category="uncertainty", impact=Impact(u.cost_impact), field_path=u.field_path,
                   description=u.description, action="Confirmar dato")
    for a in job.assumptions:
        if not a.approved_by:
            ctx.review(severity=Severity.MEDIUM, category="assumption", impact=Impact(a.cost_impact), field_path=a.field_path,
                       description=f"Suposición sin aprobar: {a.assumption}", action="Aprobar o rechazar suposición")
    thr = ctx.rules.get("risk.thresholds.low_ai_confidence")
    for path, t in iter_tracked(job):
        if t.source_status == SourceStatus.INFERRED and Decimal(str(t.confidence)) < thr:
            ctx.review(severity=Severity.LOW, category="inference", impact=Impact.MEDIUM, field_path=path,
                       description=f"Valor inferido con baja confianza ({t.confidence:.2f}): {path} = {getattr(t.value, 'value', t.value)}",
                       action="Confirmar o corregir (override auditable)")
    for r in job.review_items:  # alertas del intérprete
        ctx.reviews.append(r)


def calculate(job: ManufacturingJob, master: CostMaster, rules: RuleSet, as_of: date) -> CostResult:
    original_hash = input_hash(job)
    job = job.model_copy(deep=True)  # normalizaciones no tocan el original
    p = job.project
    currency = str(p.currency.value) if p.currency.known else str(rules.get("money.costing_currency"))
    ctx = CostContext(job=job, master=master, rules=rules, as_of=as_of, currency=currency)

    if not p.currency.known:
        ctx.review(severity=Severity.CRITICAL, category="project", impact=Impact.HIGH, field_path="project.currency",
                   description=f"Moneda de cotización desconocida; costeo interno en {currency} (regla money.costing_currency)",
                   action="Confirmar moneda de cotización")
    if not p.quantity.known:
        ctx.review(severity=Severity.CRITICAL, category="project", impact=Impact.HIGH, field_path="project.quantity",
                   description="Cantidad desconocida: se muestran costos unitarios y de setup, sin total",
                   action="Confirmar cantidad", question="Confirmar cantidad a cotizar (y si se desean precios por volumen).")

    mults = component_multipliers(ctx)
    for idx, comp in enumerate(job.components):
        if comp.deleted:
            continue
        path = f"components[{idx}]"
        mult = mults.get(comp.component_id)
        if mult is None:
            ctx.missing(category="assembly", description=f"{comp.component_id}: cantidad por ensamble", component_id=comp.component_id,
                        reason="quantity_per_parent desconocida (propia o de un padre)", severity=Severity.CRITICAL,
                        field_path=f"{path}.quantity_per_parent",
                        question=f"Confirmar cuántas piezas de {comp.description} lleva cada ensamble.")
            continue
        _cost_component(ctx, comp, path, mult)

    cost_quality(ctx)
    cost_packaging(ctx)
    cost_logistics(ctx)
    cost_engineering(ctx)
    _epistemic_reviews(ctx)

    ctx.reviews.sort(key=lambda r: (SEVERITY_ORDER[r.severity], {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[r.cost_impact.value], r.review_id))
    coverage = _coverage(ctx.lines)
    return CostResult(
        engine_version=ENGINE_VERSION, schema_version=SCHEMA_VERSION, rule_set_ref=rules.ref,
        cost_master_version=master.version, input_hash=original_hash, as_of_date=as_of, currency=currency,
        uses_sample_data=bool(master.is_sample or rules.is_sample or any(s.is_sample for l in ctx.lines for s in l.sources)),
        lines=ctx.lines, review_items=ctx.reviews, coverage=coverage,
        is_partial=any(l.status == LineStatus.MISSING for l in ctx.lines),
        quantity=int(p.quantity.value) if p.quantity.known else None,
    )


def _cost_component(ctx: CostContext, comp: Component, path: str, mult: Decimal) -> None:
    mob = comp.make_or_buy
    if mob == MakeOrBuy.BUY:
        cost_buy(ctx, comp, path, mult)
        return
    if mob == MakeOrBuy.UNKNOWN:
        ctx.review(severity=Severity.HIGH, category="make_or_buy", impact=Impact.HIGH, field_path=f"{path}.make_or_buy",
                   description=f"{comp.component_id}: no se sabe si se fabrica o se compra",
                   action="Definir MAKE/BUY", question=f"¿{comp.description} se fabrica en T&S o es componente comercial?")
        if not comp.processes and comp.material is None:
            return
    has_children = any(c.parent_component_id == comp.component_id for c in ctx.job.active_components())
    if comp.material is not None or not has_children:
        cost_material(ctx, comp, path, mult)
    for p_i, proc in enumerate(sorted(comp.processes, key=lambda x: x.routing_sequence)):
        ppath = f"{path}.processes[{comp.processes.index(proc)}]"
        fn = _DISPATCH.get(proc.process_type)
        if fn is None:
            cost_generic(ctx, comp, proc, ppath, mult)  # type: ignore[arg-type]
        else:
            fn(ctx, comp, proc, ppath, mult)


def _coverage(lines: list[CostLine]) -> Coverage:
    by: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for l in lines:
        by[l.category][1] += 1
        if l.status == LineStatus.COMPLETE:
            by[l.category][0] += 1
    pct = {k: (Decimal(v[0]) * HUNDRED / Decimal(v[1])).quantize(Decimal("0.1")) for k, v in sorted(by.items())}
    tot = sum(v[1] for v in by.values())
    ok = sum(v[0] for v in by.values())
    overall = (Decimal(ok) * HUNDRED / Decimal(tot)).quantize(Decimal("0.1")) if tot else Decimal("0")
    return Coverage(by_category=pct, overall=overall,
                    missing_items=[f"{l.description}: {l.missing_reason}" for l in lines if l.status == LineStatus.MISSING])


# ----------------------------------------------------------------------------- totals by quantity
def category_totals(result: CostResult, qty: Decimal, master: CostMaster, rules: RuleSet) -> tuple[dict[str, Decimal], list[dict]]:
    """Totales por categoría para una cantidad, incluyendo cargos mínimos (ajuste explícito, trazable)."""
    tot: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for l in result.lines:
        if l.status == LineStatus.COMPLETE:
            tot[l.category] += l.total(qty)
    adjustments = []
    rule_min = rules.get("minimum_charges", {}) or {}
    for cat in list(tot.keys()):
        mins = [Decimal(rule_min.get(cat, 0))]
        rate = master.rate(cat)
        if rate and rate.minimum_charge:
            mins.append(convert_money(rate.minimum_charge, rate.currency, result.currency, master, rules).converted_value)
        m = max(mins)
        if m > 0 and tot[cat] < m:
            adjustments.append({"category": cat, "calculated": str(tot[cat]), "minimum_charge": str(m),
                                "adjustment": str(m - tot[cat]), "source": "rules.minimum_charges / cost_master.minimum_charge"})
            tot[cat] = m
    return dict(tot), adjustments

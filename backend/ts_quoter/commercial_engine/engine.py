"""Commercial Engine: costo base -> contingencia -> indirectos -> margen REAL -> redondeo.

    Selling Price = Total Internal Cost / (1 − margin)      (nunca Cost × 1.35)

Separación (sec. 66): costo directo | overhead manufactura | overhead administrativo |
costos comerciales | contingencia | margen. Cada paso queda en ``steps`` con su fórmula.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..cost_engine.engine import category_totals
from ..money import q2, round_commercial
from ..rules.loader import RuleSet
from ..schemas.common import SourceStatus
from ..schemas.cost_master import CostMaster
from ..schemas.manufacturing import ManufacturingJob
from ..schemas.results import CostResult, PriceStep, QuantityBreak, QuoteRecommendation, RiskResult
from ..schemas.walk import iter_tracked

ZERO, ONE, HUNDRED = Decimal("0"), Decimal("1"), Decimal("100")
COMMERCIAL_CATEGORIES = {"logistics"}  # se reportan como costos comerciales, no de manufactura


class PriceBreakdown:
    def __init__(self, cost: CostResult, risk: RiskResult, master: CostMaster, rules: RuleSet, job: ManufacturingJob,
                 qty: Decimal, margin_pct: Decimal) -> None:
        totals, self.min_adjustments = category_totals(cost, qty, master, rules)
        cont_pct = {l.category: l.pct for l in risk.contingency_lines}
        rew_pct: dict[str, Decimal] = {}
        for l in risk.rework_lines:
            rew_pct[l.category] = rew_pct.get(l.category, ZERO) + l.pct
        mfg = {k: v for k, v in totals.items() if k not in COMMERCIAL_CATEGORIES}
        self.base = sum(mfg.values(), ZERO)
        self.logistics = sum((v for k, v in totals.items() if k in COMMERCIAL_CATEGORIES), ZERO)
        self.contingency = sum((v * cont_pct.get(k, ZERO) / HUNDRED for k, v in totals.items()), ZERO)
        self.rework = sum((v * rew_pct.get(k, ZERO) / HUNDRED for k, v in totals.items()), ZERO)
        self.adjusted = self.base + self.contingency + self.rework
        c = rules.get("commercial")
        self.mfg_oh = self.adjusted * c["manufacturing_overhead_pct"] / HUNDRED
        self.adm_oh = self.adjusted * c["administrative_overhead_pct"] / HUNDRED
        self.rush = self.adjusted * rules.lookup("commercial.rush_premium_pct", job.project.rush.value) / HUNDRED
        self.commercial = self.logistics + (self.adjusted + self.mfg_oh + self.adm_oh) * c["commercial_cost_pct"] / HUNDRED
        self.total_internal = self.adjusted + self.mfg_oh + self.adm_oh + self.commercial + self.rush
        if margin_pct >= HUNDRED:
            raise ValueError("margen debe ser < 100%")
        self.price = self.total_internal / (ONE - margin_pct / HUNDRED)
        self.markup = ((self.price / self.total_internal - ONE) * HUNDRED) if self.total_internal else ZERO


def recommend(job: ManufacturingJob, cost: CostResult, risk: RiskResult, master: CostMaster, rules: RuleSet,
              approved_price: Optional[Decimal] = None) -> QuoteRecommendation:
    c = rules.get("commercial")
    ci = job.commercial_inputs
    margin = Decimal(str(ci.target_margin_pct)) if ci.target_margin_pct is not None else c["default_margin_pct"]
    margin_src = "commercial_inputs.target_margin_pct (humano)" if ci.target_margin_pct is not None else rules.rule_ref("commercial.default_margin_pct")
    qty_known = cost.quantity is not None
    qty = Decimal(cost.quantity or 1)
    b = PriceBreakdown(cost, risk, master, rules, job, qty, margin)
    mode, step = str(c["rounding"]["mode"]), Decimal(c["rounding"]["step"])

    unit_price = b.price / qty
    unit_rounded = round_commercial(unit_price, mode, step)
    rounded_total = unit_rounded * qty

    steps = [
        PriceStep(label="Base manufacturing cost", amount=q2(b.base), formula=f"Σ líneas completas (setup + por unidad × {qty}) excl. logística"),
        PriceStep(label="Risk contingency", amount=q2(b.contingency), formula=f"Σ categoría × pct ({risk.contingency_mode})"),
        PriceStep(label="Rework contingency", amount=q2(b.rework), formula="Σ categoría × pct retrabajo"),
        PriceStep(label="Adjusted manufacturing cost", amount=q2(b.adjusted), formula="base + contingencia + retrabajo"),
        PriceStep(label="Manufacturing overhead", amount=q2(b.mfg_oh), formula=f"ajustado × {c['manufacturing_overhead_pct']}%"),
        PriceStep(label="Administrative overhead", amount=q2(b.adm_oh), formula=f"ajustado × {c['administrative_overhead_pct']}%"),
        PriceStep(label="Commercial costs", amount=q2(b.commercial), formula=f"logística + (ajustado + overheads) × {c['commercial_cost_pct']}%"),
        PriceStep(label="Rush premium", amount=q2(b.rush), formula=f"ajustado × rush_premium[{job.project.rush.value}]"),
        PriceStep(label="Total internal cost", amount=q2(b.total_internal), formula="ajustado + overheads + comerciales + rush"),
        PriceStep(label="Suggested sell price", amount=q2(b.price), formula=f"total_interno / (1 − {margin}%)  [margen desde {margin_src}]"),
        PriceStep(label="Rounded price", amount=q2(rounded_total), formula=f"round_{mode}(precio_unitario, {step}) × {qty}"),
    ]

    breaks = []
    for qb in sorted(set(ci.quantity_breaks + ([int(qty)] if qty_known else []))):
        bq = PriceBreakdown(cost, risk, master, rules, job, Decimal(qb), margin)
        up = bq.price / qb
        breaks.append(QuantityBreak(quantity=qb, base_cost=q2(bq.base), contingency=q2(bq.contingency + bq.rework),
                                    total_internal_cost=q2(bq.total_internal), suggested_price_total=q2(bq.price),
                                    suggested_unit_price=q2(up), rounded_unit_price=round_commercial(up, mode, step)))

    stop = _stop_conditions(job, cost, rules)
    approvals = _approval_gates(risk, rules)
    warnings = []
    if cost.uses_sample_data:
        warnings.append("SAMPLE DATA: el cálculo usa tarifas/precios/reglas de ejemplo; no usar para cotizar.")
    if b.min_adjustments:
        warnings += [f"Cargo mínimo aplicado en {a['category']}: +{q2(Decimal(a['adjustment']))}" for a in b.min_adjustments]
    if cost.is_partial:
        warnings.append(f"PARTIAL COST: {len(cost.coverage.missing_items)} elementos sin costo; el total NO es final.")

    if stop and not (ci.proceed_with_assumptions and ci.proceed_approved_by):
        status = "BLOCKED"
    elif stop:
        status = "PROCEED_WITH_ASSUMPTIONS"
    elif cost.is_partial:
        status = "PARTIAL_COST"
    else:
        status = "RECOMMENDED"

    questions = [r.question for r in cost.review_items if r.question]
    notes = [f"Precio basado en plano {job.project.drawing_number.value or '¿?'} rev. {job.project.drawing_revision.value or '¿?'}"]
    notes += [f"Suposición: {a.assumption}" for a in job.assumptions]
    notes += [f"Supuesto de dato inferido: {p} = {t.value}" for p, t in iter_tracked(job)
              if t.source_status == SourceStatus.INFERRED and any(k in p for k in ("grade", "final_finish", "side"))]

    return QuoteRecommendation(
        status=status, autoquote_class=risk.cei_classification, currency=cost.currency,
        quantity=cost.quantity, steps=steps,
        base_manufacturing_cost=q2(b.base), risk_contingency=q2(b.contingency), rework_contingency=q2(b.rework),
        adjusted_manufacturing_cost=q2(b.adjusted), manufacturing_overhead=q2(b.mfg_oh),
        administrative_overhead=q2(b.adm_oh), commercial_costs=q2(b.commercial), rush_premium=q2(b.rush),
        total_internal_cost=q2(b.total_internal), target_margin_pct=margin,
        markup_pct_informative=q2(b.markup), calculated_price=q2(b.price), rounded_price=q2(rounded_total),
        approved_price=approved_price, unit_price_rounded=unit_rounded, quantity_breaks=breaks,
        stop_reasons=stop, required_approvals=approvals, quote_notes=notes,
        technical_questions=questions[:10], warnings=warnings,
        extra={"minimum_charge_adjustments": b.min_adjustments,
               "quantity_basis": str(qty) + ("" if qty_known else " (cantidad desconocida: base 1)")},
    )


def _stop_conditions(job: ManufacturingJob, cost: CostResult, rules: RuleSet) -> list[str]:
    stop = []
    crit = set(rules.get("commercial.stop_conditions.critical_categories"))
    miss = [l for l in cost.lines if l.status.value == "missing" and l.category in crit]
    if miss:
        stop.append("Costo crítico faltante: " + "; ".join(l.description for l in miss[:5]))
    if not job.project.quantity.known:
        stop.append("Cantidad desconocida")
    if not job.project.currency.known:
        stop.append("Moneda desconocida")
    mat_conf = [c for c in job.conflicts if not c.resolved and "material" in c.field_path]
    mat_conf += [p for p, t in iter_tracked(job) if t.source_status == SourceStatus.CONFLICTING and "material" in p]
    if mat_conf:
        stop.append("Conflicto mayor de material sin resolver")
    if job.interpretation_quality.missing_pages:
        stop.append("Faltan páginas críticas del dibujo")
    return stop


def _approval_gates(risk: RiskResult, rules: RuleSet) -> list[str]:
    metrics = {"cei": risk.cei, "overall_risk_level": risk.overall_risk, "overall_score": risk.overall_score}
    req = []
    for g in rules.get("commercial.approval_gates"):
        v = metrics.get(str(g["metric"]))
        op, ref = g["op"], g["value"]
        hit = (op == "lt" and v < ref) or (op == "gt" and v > ref) or (op == "in" and v in ref)
        if hit:
            req.append(f"{g['requires']} ({g['metric']} {op} {ref}; actual {v})")
    return req

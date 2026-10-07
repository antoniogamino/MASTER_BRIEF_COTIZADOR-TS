"""Risk Engine — independiente del margen.

Cada factor activado aporta ``weight × severity`` puntos a su categoría (tope 100). Cada driver lleva
la evidencia concreta que lo activó (sec. 109: explicar exactamente qué genera el riesgo).
Pesos y umbrales viven en el rule set (y pueden sobreescribirse desde COST_MASTER > RiskParameters).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Callable, Optional

from ..cost_engine.engine import category_totals
from ..process_engine.common import enum_val, max_dim, tightest_tolerance
from ..rules.loader import RuleSet
from ..schemas.common import SourceStatus
from ..schemas.cost_master import CostMaster
from ..schemas.manufacturing import ManufacturingJob
from ..schemas.results import CategoryRisk, ContingencyLine, CostResult, LineStatus, RiskDriver, RiskResult
from ..schemas.walk import iter_tracked
from .cei import compute_cei

RISK_MODEL_VERSION = "risk-model/0.1.0"
ZERO, ONE, HUNDRED = Decimal("0"), Decimal("1"), Decimal("100")
Eval = Callable[["RiskInputs"], Optional[tuple[Decimal, str]]]


class RiskInputs:
    """Hechos pre-calculados para evaluar factores."""

    def __init__(self, job: ManufacturingJob, cost: CostResult, master: CostMaster, rules: RuleSet) -> None:
        from ..cost_engine.context import CostContext

        self.job, self.cost, self.master, self.rules = job, cost, master, rules
        self.ctx = CostContext(job=job, master=master, rules=rules, as_of=cost.as_of_date, currency=cost.currency)
        self.th = rules.get("risk.thresholds")
        self.missing = [l for l in cost.lines if l.status == LineStatus.MISSING]
        self.reviews = cost.review_items
        self.comps = job.active_components()
        self.welds = [(c, j) for c in self.comps for p in c.processes if p.process_type == "welding" for j in p.joints]
        self.mat_sources = [s for l in cost.lines if l.category == "material" for s in l.sources if s.kind == "material_price"]
        self.fx_sources = [s for l in cost.lines for s in l.sources if s.kind == "fx"]

    def reviews_on(self, *needles: str) -> list:
        return [r for r in self.reviews if r.field_path and any(n in r.field_path for n in needles)]


def _sev(n: int | float | Decimal, full: int | float) -> Decimal:
    return min(ONE, Decimal(str(n)) / Decimal(str(full)))


# ----------------------------------------------------------------------------- factor evaluators
def _missing_dimensions(x: RiskInputs):
    rv = [r for r in x.reviews_on("geometry", "weld_length", ".area", "cut_length", "rolled_length") if r.severity.value in ("HIGH", "CRITICAL")]
    return (_sev(len(rv), 3), f"{len(rv)} dimensiones faltantes: " + "; ".join(r.field_path for r in rv[:4])) if rv else None


def _ambiguous_welds(x: RiskInputs):
    rv = x.reviews_on("joints")
    return (_sev(len(rv), 4), f"{len(rv)} datos de soldadura ambiguos/desconocidos") if rv else None


def _missing_material(x: RiskInputs):
    m = [l for l in x.missing if l.category == "material"]
    return (ONE, "; ".join(l.missing_reason or "" for l in m[:3])) if m else None


def _missing_finish(x: RiskInputs):
    rv = x.reviews_on("final_finish")
    return (ONE, "acabado final no especificado") if rv else None


def _conflicts(x: RiskInputs):
    c = [c for c in x.job.conflicts if not c.resolved]
    st = [p for p, t in iter_tracked(x.job) if t.source_status == SourceStatus.CONFLICTING]
    n = len(c) + len(st)
    return (_sev(n, 2), f"{n} conflictos sin resolver") if n else None


def _low_ai_conf(x: RiskInputs):
    iq = x.job.interpretation_quality
    if iq.interpreter == "manual":
        return None
    thr = x.th["low_ai_confidence"]
    if iq.interpretation_confidence is not None and Decimal(str(iq.interpretation_confidence)) < thr:
        return ONE, f"confianza de interpretación {iq.interpretation_confidence} < {thr}"
    inferred = [t.confidence for _, t in iter_tracked(x.job) if t.source_status == SourceStatus.INFERRED]
    if inferred:
        avg = Decimal(str(sum(inferred) / len(inferred)))
        if avg < thr:
            return ONE, f"confianza promedio de campos inferidos {avg:.2f} < {thr}"
    return None


def _flag(attr: str, label: str):
    def f(x: RiskInputs):
        return (ONE, label) if getattr(x.job.interpretation_quality, attr) else None
    return f


def _poor_drawing(x: RiskInputs):
    s = x.job.interpretation_quality.drawing_quality_score
    if s is not None and s < 60:
        return _sev(60 - s, 60), f"drawing_quality_score={s}"
    return None


def _unclear_qty(x: RiskInputs):
    return (ONE, "cantidad desconocida") if not x.job.project.quantity.known else None


def _first_time(x: RiskInputs):
    ft = x.job.project.first_time_build
    if not ft.known:
        return Decimal("0.5"), "se desconoce si es primera fabricación"
    return (ONE, "primera fabricación") if ft.value else None


def _tight_tol(x: RiskInputs):
    tols = [t for c in x.comps if (t := tightest_tolerance(c, x.ctx)) is not None]
    if not tols:
        return None
    t = min(tols)
    if t <= Decimal("0.05"):
        return ONE, f"tolerancia más cerrada ±{t} mm"
    if t <= Decimal("0.1"):
        return Decimal("0.6"), f"tolerancia más cerrada ±{t} mm"
    return None


def _weld_density(x: RiskInputs):
    weld_mm = sum((x.ctx.val(j.weld_length, "mm") or ZERO) for _, j in x.welds if j.weld_length.known)
    kg = sum((Decimal(l.quantities.get("net_kg", "0")) for l in x.cost.lines if l.category == "material"), ZERO)
    if weld_mm <= 0 or kg <= 0:
        return None
    d = weld_mm / kg
    thr = x.th["high_weld_density_mm_per_kg"]
    return (_sev(d, thr * 2), f"densidad de soldadura {d:.0f} mm/kg (umbral {thr})") if d > thr else None


def _sanitary(x: RiskInputs):
    s = [j.joint_id for _, j in x.welds if j.sanitary.known and j.sanitary.value]
    pol = [p.process_id for c in x.comps for p in c.processes if p.process_type == "surface_polishing" and p.polish_kind == "sanitary"]
    return (ONE, f"requisito sanitario: {', '.join(s + pol)}") if (s or pol) else None


def _manual_finishing(x: RiskInputs):
    hrs = defaultdict(lambda: ZERO)
    for l in x.cost.lines:
        hrs[l.category] += l.hours_per_unit
    tot = sum(hrs.values(), ZERO)
    fin = hrs["surface_polishing"] + hrs["weld_finishing"]
    if tot <= 0 or fin <= 0:
        return None
    share = fin / tot
    return (_sev(share, Decimal("0.6")), f"acabado manual = {share * 100:.0f}% de horas por unidad") if share > Decimal("0.2") else None


def _difficult_access(x: RiskInputs):
    hard = {"difficult", "very_difficult"}
    items = [j.joint_id for _, j in x.welds if j.accessibility.known and enum_val(j.accessibility.value) in hard]
    items += [p.process_id for c in x.comps for p in c.processes
              if hasattr(p, "accessibility") and p.accessibility.known and enum_val(p.accessibility.value) in hard]
    return (_sev(len(items), 2), f"acceso difícil: {', '.join(items)}") if items else None


def _small_precision(x: RiskInputs):
    for c in x.comps:
        md, tol = max_dim(c, x.ctx), tightest_tolerance(c, x.ctx)
        if md is not None and tol is not None and md <= x.th["small_precision_part_max_dim_mm"] and tol <= Decimal("0.1"):
            return ONE, f"{c.component_id}: pieza pequeña ({md} mm) con tolerancia ±{tol}"
    return None


def _large_part(x: RiskInputs):
    for c in x.comps:
        md = max_dim(c, x.ctx)
        if md is not None and md >= x.th["large_part_min_dim_mm"]:
            return ONE, f"{c.component_id}: dimensión mayor {md} mm"
    return None


def _custom_fixture(x: RiskInputs):
    f = [p.process_id for c in x.comps for p in c.processes if getattr(p, "special_fixture", False)]
    f += [fx.fixture_id for fx in x.job.engineering.fixtures]
    return (ONE, f"fixture especial: {', '.join(f)}") if f else None


def _unknown_process_time(x: RiskInputs):
    proc_cats = {"laser_cutting", "bending", "rolling", "welding", "surface_polishing", "weld_finishing", "machining", "generic_process", "outsourcing"}
    m = [l for l in x.missing if l.category in proc_cats]
    return (_sev(len(m), 3), f"{len(m)} procesos sin costo: " + "; ".join(l.description for l in m[:3])) if m else None


def _old_price(x: RiskInputs):
    recs = [s.recency for s in x.mat_sources]
    if "obsolete" in recs:
        return ONE, "precio de material obsoleto"
    if "stale" in recs:
        return Decimal("0.6"), "precio de material viejo (stale)"
    return None


def _parametric(x: RiskInputs):
    if not x.mat_sources:
        return None
    d = [s for s in x.mat_sources if s.level == "D"]
    return (Decimal(len(d)) / Decimal(len(x.mat_sources)), f"{len(d)}/{len(x.mat_sources)} precios de material paramétricos (nivel D)") if d else None


def _estimated_rate(x: RiskInputs):
    keys = {s.key for l in x.cost.lines for s in l.sources if s.kind == "process_rate"}
    est = [k for k in keys if (r := x.master.rate(k)) and r.estimated]
    return (_sev(len(est), 2), f"tarifas estimadas: {', '.join(sorted(est))}") if est else None


def _missing_cost(x: RiskInputs):
    if not x.cost.lines:
        return ONE, "sin líneas de costo"
    share = Decimal(len(x.missing)) / Decimal(len(x.cost.lines))
    return (min(ONE, share * 3), f"{len(x.missing)}/{len(x.cost.lines)} líneas sin costo") if x.missing else None


def _foreign_ccy(x: RiskInputs):
    return (Decimal("0.5"), f"{len(x.fx_sources)} conversiones de moneda") if x.fx_sources else None


def _unknown_consumables(x: RiskInputs):
    return (ONE, "consumibles de soldadura sin precio") if any(l.category == "welding_consumables" for l in x.missing) else None


def _long_validity(x: RiskInputs):
    v = x.job.project.quote_validity_days
    thr = x.th["long_validity_days"]
    return (_sev(v - thr, thr), f"vigencia {v} días > {thr}") if v > thr else None


def _export(x: RiskInputs):
    e = x.job.project.export
    if not e.known:
        return Decimal("0.5"), "se desconoce si es exportación"
    return (ONE, "exportación") if e.value else None


def _imported(x: RiskInputs):
    imp = [c.component_id for c in x.comps if c.buy and c.buy.currency and c.buy.currency != x.cost.currency]
    return (_sev(len(imp), 2), f"componentes importados: {', '.join(imp)}") if imp else None


def _freight(x: RiskInputs):
    e = x.job.project.export
    if not (e.known and e.value):
        return None
    fr = [l for l in x.job.logistics if l.item_key == "freight"]
    if not fr or not fr[0].cost.known:
        return ONE, "exportación sin costo de flete confirmado"
    return None


def _small_qty(x: RiskInputs):
    q = x.job.project.quantity
    return (ONE, f"cantidad {q.value}") if q.known and q.value <= x.th["small_quantity_max"] else None


def _expedite(x: RiskInputs):
    r = x.job.project.rush.value
    return {"urgent": (Decimal("0.5"), "pedido urgente"), "expedite": (ONE, "pedido expedito")}.get(r)


def _fx_exposure(x: RiskInputs):
    if not x.fx_sources:
        return None
    return Decimal("0.6"), "costos en moneda distinta a la de cotización (exposición FX)"


def _long_lead(x: RiskInputs):
    thr = x.th["long_supplier_lead_days"]
    l = [c.component_id for c in x.comps if c.buy and c.buy.lead_time_days and c.buy.lead_time_days > thr]
    return (ONE, f"lead time proveedor > {thr} días: {', '.join(l)}") if l else None


EVALUATORS: dict[str, dict[str, Eval]] = {
    "interpretation": {
        "missing_dimensions": _missing_dimensions, "ambiguous_welds": _ambiguous_welds, "missing_material": _missing_material,
        "missing_finish": _missing_finish, "conflicts": _conflicts, "low_ai_confidence": _low_ai_conf,
        "poor_drawing_quality": _poor_drawing, "missing_pages": _flag("missing_pages", "faltan páginas del dibujo"),
        "unreadable_notes": _flag("unreadable_notes", "notas ilegibles"),
        "multiple_revisions": _flag("multiple_revisions", "múltiples revisiones en documentos"),
        "unclear_units": _flag("unclear_units", "unidades poco claras"), "unclear_quantity": _unclear_qty,
    },
    "manufacturing": {
        "first_time_build": _first_time, "tight_tolerance": _tight_tol, "high_weld_density": _weld_density,
        "sanitary_requirement": _sanitary, "manual_finishing": _manual_finishing, "difficult_access": _difficult_access,
        "small_precision_part": _small_precision, "custom_fixture": _custom_fixture,
        "unknown_process_time": _unknown_process_time, "large_part": _large_part,
    },
    "cost_data": {
        "old_material_price": _old_price, "parametric_cost_only": _parametric, "estimated_machine_rate": _estimated_rate,
        "missing_cost": _missing_cost, "foreign_currency": _foreign_ccy, "unknown_consumables": _unknown_consumables,
    },
    "commercial": {
        "long_validity_period": _long_validity, "export": _export, "imported_component": _imported,
        "freight_uncertainty": _freight, "small_quantity": _small_qty, "expedite": _expedite,
        "foreign_currency_exposure": _fx_exposure,
    },
    "delivery": {"expedite": _expedite, "long_supplier_lead": _long_lead, "first_time_build": _first_time},
}


def level_for(score: Decimal, rules: RuleSet) -> str:
    for row in rules.get("risk.levels"):
        if score <= row["max_score"]:
            return str(row["level"])
    return str(rules.get("risk.levels")[-1]["level"])


def _category(name: str, x: RiskInputs, overrides: dict[str, Decimal]) -> CategoryRisk:
    weights = x.rules.get(f"risk.factors.{name}")
    drivers: list[RiskDriver] = []
    for key, w in weights.items():
        fn = EVALUATORS[name].get(key)
        if fn is None:
            continue
        res = fn(x)
        if res is None:
            continue
        sev, ev = res
        w = overrides.get(key, w)
        sev = sev.quantize(Decimal("0.01"))
        drivers.append(RiskDriver(category=name, factor=key, weight=w, severity=sev,
                                  points=(w * sev).quantize(Decimal("0.01")), evidence=ev))
    score = min(HUNDRED, sum((d.points for d in drivers), ZERO))
    drivers.sort(key=lambda d: -d.points)
    return CategoryRisk(score=score, level=level_for(score, x.rules), drivers=drivers)


def _interp_band(score: Decimal, level: str, rules: RuleSet) -> Decimal:
    lo, hi = rules.get(f"risk.contingency_bands_pct.{level}")
    rows = rules.get("risk.levels")
    idx = [str(r["level"]) for r in rows].index(level)
    lower = rows[idx - 1]["max_score"] if idx > 0 else ZERO
    upper = rows[idx]["max_score"]
    t = (score - lower) / (upper - lower) if upper > lower else ZERO
    return lo + (hi - lo) * max(ZERO, min(ONE, t))


def assess(job: ManufacturingJob, cost: CostResult, master: CostMaster, rules: RuleSet,
           quantity: Optional[int] = None) -> RiskResult:
    x = RiskInputs(job, cost, master, rules)
    overrides = {o.factor_key: o.weight for o in master.risk_parameters}
    cats = {n: _category(n, x, overrides) for n in EVALUATORS}
    cw = rules.get("risk.category_weights")
    overall = sum((cats[n].score * cw[n] for n in cats), ZERO).quantize(Decimal("0.01"))
    overall_level = level_for(overall, rules)

    qty = Decimal(quantity or cost.quantity or 1)
    totals, _ = category_totals(cost, qty, master, rules)
    mode = str(rules.get("risk.contingency_mode"))
    lines: list[ContingencyLine] = []
    if mode == "global":
        pct = _interp_band(overall, overall_level, rules)
        for cat, amt in sorted(totals.items()):
            lines.append(ContingencyLine(category=cat, base_amount=amt, pct=pct, amount=amt * pct / HUNDRED,
                                         basis=f"global: overall {overall} ({overall_level}) → banda {rules.get(f'risk.contingency_bands_pct.{overall_level}')}% interpolada"))
    else:
        mult = rules.lookup("risk.per_process_level_multiplier", overall_level)
        for cat, amt in sorted(totals.items()):
            base = rules.lookup("risk.per_process_base_pct", cat, rules.get("risk.per_process_base_pct.generic_process"))
            pct = base * mult
            lines.append(ContingencyLine(category=cat, base_amount=amt, pct=pct, amount=amt * pct / HUNDRED,
                                         basis=f"per_process: base {base}% × multiplicador {mult} (riesgo global {overall_level})"))

    rework = _rework(x, totals)
    cont_total = sum((l.amount for l in lines), ZERO)
    rew_total = sum((l.amount for l in rework), ZERO)
    base_total = sum(totals.values(), ZERO)
    eff = (cont_total * HUNDRED / base_total).quantize(Decimal("0.01")) if base_total else ZERO
    cei, cei_class, comps = compute_cei(x, cats)
    return RiskResult(
        risk_model_version=RISK_MODEL_VERSION, rule_set_ref=rules.ref,
        interpretation_risk=cats["interpretation"], manufacturing_risk=cats["manufacturing"],
        cost_data_risk=cats["cost_data"], commercial_risk=cats["commercial"], delivery_risk=cats["delivery"],
        overall_score=overall, overall_risk=overall_level, contingency_mode=mode, contingency_lines=lines,
        rework_lines=rework, contingency_total=cont_total, rework_total=rew_total, contingency_pct_effective=eff,
        cei=cei, cei_classification=cei_class, cei_components=comps, quantity_basis=qty,
    )


def _rework(x: RiskInputs, totals: dict[str, Decimal]) -> list[ContingencyLine]:
    r = x.rules
    out: list[ContingencyLine] = []
    tt = _tight_tol(x)
    if tt and totals.get("machining"):
        pct = r.get("risk.rework.tight_tolerance_pct")
        out.append(ContingencyLine(category="machining", base_amount=totals["machining"], pct=pct,
                                   amount=totals["machining"] * pct / HUNDRED, basis=f"retrabajo por tolerancia: {tt[1]}"))
    complex_w = [j.joint_id for _, j in x.welds if (j.penetration.known and j.penetration.value == "full") or (j.sanitary.known and j.sanitary.value)]
    if complex_w and totals.get("welding"):
        pct = r.get("risk.rework.complex_welding_pct")
        out.append(ContingencyLine(category="welding", base_amount=totals["welding"], pct=pct,
                                   amount=totals["welding"] * pct / HUNDRED, basis=f"retrabajo soldadura compleja: {', '.join(complex_w)}"))
    cosmetic = {"#8", "Ra<=0.6", "Ra<=0.4"}
    from ..process_engine.finishing import normalize_finish
    hc = [p.process_id for c in x.comps for p in c.processes
          if p.process_type == "surface_polishing" and p.final_finish.known and normalize_finish(str(p.final_finish.value)) in cosmetic]
    if hc and totals.get("surface_polishing"):
        pct = r.get("risk.rework.high_cosmetic_pct")
        out.append(ContingencyLine(category="surface_polishing", base_amount=totals["surface_polishing"], pct=pct,
                                   amount=totals["surface_polishing"] * pct / HUNDRED, basis=f"retrabajo cosmético: {', '.join(hc)}"))
    return out

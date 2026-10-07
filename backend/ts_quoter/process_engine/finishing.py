"""Pulido de superficie y acabado de soldadura — modelos SEPARADOS (sec. 37-39)."""

from __future__ import annotations

from decimal import Decimal

from ..cost_engine.context import CostContext
from ..schemas.common import Severity
from ..schemas.manufacturing import Component, Side, SurfacePolishing, WeldFinishing
from ..schemas.results import TraceInput
from .common import apply_time_overrides, enum_val, factor, priced_hours

HUNDRED = Decimal("100")
K = Decimal("1000")


def normalize_finish(raw: str) -> str:
    """'Ra ≤ 0.8 µm' -> 'Ra<=0.8'; '# 4' -> '#4'. No convierte acabado visual a Ra."""
    s = raw.replace("≤", "<=").replace("µm", "").replace("um", "").replace(" ", "")
    if s.lower().startswith("no.") or s.lower().startswith("no"):
        s = "#" + s.lstrip("Nno.")
    return s


def _add_consumables_pct(line, ctx: CostContext, pct_path: str) -> None:
    if line is None:
        return
    pct = ctx.rules.get(pct_path)
    line.one_time += line.one_time * pct / HUNDRED
    line.per_unit += line.per_unit * pct / HUNDRED
    line.inputs["consumables_pct"] = ctx.rule_input(pct_path, pct, "%")
    line.formula += f" ; × (1 + consumables {pct}%)"


def cost_surface_polishing(ctx: CostContext, comp: Component, p: SurfacePolishing, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    inputs: dict = {}
    notes: list[str] = []
    label = f"{cid}: pulido {p.polish_kind}"
    if not p.run_time_override.known:
        if not p.final_finish.known:
            ctx.missing(category="surface_polishing", description=label, component_id=cid, process_id=p.process_id,
                        reason="acabado final no especificado (no se asume #4)", severity=Severity.HIGH,
                        field_path=f"{path}.final_finish", question=f"Confirmar acabado superficial requerido para {comp.description} (p.ej. #4, Ra ≤ 0.8 µm).")
            return
        if not p.area.known:
            ctx.missing(category="surface_polishing", description=label, component_id=cid, process_id=p.process_id,
                        reason="área a pulir desconocida", severity=Severity.HIGH, field_path=f"{path}.area")
            return
        sides = enum_val(p.sides.value) if p.sides.known else None
        if sides in (None, Side.UNKNOWN.value):
            ctx.missing(category="surface_polishing", description=label, component_id=cid, process_id=p.process_id,
                        reason="no está claro si se pulen uno o ambos lados", severity=Severity.HIGH, field_path=f"{path}.sides",
                        question=f"Confirmar si {comp.description} requiere pulido en ambas caras o sólo en la cara visible/de contacto.")
            return
        fin = normalize_finish(str(p.final_finish.value))
        rate = r.lookup("polishing.rate_m2_per_hr", fin, None)
        if rate is None:
            ctx.missing(category="surface_polishing", description=label, component_id=cid, process_id=p.process_id,
                        reason=f"sin tasa de pulido en reglas para acabado '{fin}'", severity=Severity.HIGH)
            return
        area = ctx.val(p.area, "m2")
        sm = r.lookup("polishing.side_multiplier", sides)
        gf = r.lookup("polishing.geometry_factor", p.geometry_type)
        inputs.update(area=ctx.ti(p.area, f"{path}.area"), final_finish=ctx.ti(p.final_finish, f"{path}.final_finish"),
                      rate=ctx.rule_input("polishing.rate_m2_per_hr", rate, "m2/hr", key=fin),
                      side_multiplier=TraceInput(value=str(sm), source=f"{r.rule_ref('polishing.side_multiplier')}[{sides}] ← {path}.sides"),
                      geometry_factor=ctx.rule_input("polishing.geometry_factor", gf, key=p.geometry_type))
        af = factor(ctx, p.accessibility, "polishing.accessibility_factor", f"{path}.accessibility", inputs, "accessibility_factor", "surface_polishing", f"accesibilidad de pulido ({cid})")
        run = area * sm / rate * gf * af
        formula = "run = area × sides / rate(finish) × geometry_f × accessibility_f"
    else:
        run = Decimal("0")
        formula = "tiempo capturado manualmente"
    setup, run = apply_time_overrides(ctx, p, path, Decimal("0"), run, inputs, notes)
    line = priced_hours(ctx, rate_key=str(r.get("polishing.rate_key")), category="surface_polishing", comp=comp,
                        process_id=p.process_id, path=path, h_one=setup, h_unit_piece=run, mult=mult, formula=formula,
                        inputs=inputs, rule_refs=[r.rule_ref("polishing")], description=label, notes=notes)
    _add_consumables_pct(line, ctx, "polishing.consumables_pct_of_labor")


def cost_weld_finishing(ctx: CostContext, comp: Component, p: WeldFinishing, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    inputs: dict = {}
    notes: list[str] = []
    label = f"{cid}: acabado de soldadura ({p.finishing_kind})"
    if not p.run_time_override.known:
        if not p.weld_length.known:
            ctx.missing(category="weld_finishing", description=label, component_id=cid, process_id=p.process_id,
                        reason="longitud de soldadura a acabar desconocida", severity=Severity.HIGH, field_path=f"{path}.weld_length")
            return
        sides = enum_val(p.sides.value) if p.sides.known else None
        if sides in (None, Side.UNKNOWN.value):
            ctx.missing(category="weld_finishing", description=label, component_id=cid, process_id=p.process_id,
                        reason="lados a acabar desconocidos", severity=Severity.HIGH, field_path=f"{path}.sides",
                        question=f"Confirmar si el cordón de {comp.description} debe quedar difuminado/al ras en interior, exterior o ambos.")
            return
        L = ctx.val(p.weld_length, "mm") / K
        rate = r.lookup("weld_finishing.rate_m_per_hr", p.finishing_kind)
        sm = r.lookup("weld_finishing.side_multiplier", sides)
        inputs.update(weld_length_m=ctx.derived(L, "m", f"{path}.weld_length/1000"),
                      rate=ctx.rule_input("weld_finishing.rate_m_per_hr", rate, "m/hr", key=p.finishing_kind),
                      side_multiplier=TraceInput(value=str(sm), source=f"{r.rule_ref('weld_finishing.side_multiplier')}[{sides}]"))
        af = factor(ctx, p.accessibility, "weld_finishing.accessibility_factor", f"{path}.accessibility", inputs, "accessibility_factor", "weld_finishing", f"accesibilidad acabado soldadura ({cid})")
        if p.ra_requirement_um.known:
            raf, band = r.band("weld_finishing.ra_factor", ctx.val(p.ra_requirement_um, "um"), "max_ra")
            inputs["ra_factor"] = ctx.rule_input(band, raf)
        else:
            raf = Decimal("1")
            inputs["ra_factor"] = ctx.derived(1, "factor", "sin requisito Ra")
        run = L * sm / rate * af * raf
        formula = "run = length_m × sides / rate(kind) × accessibility_f × Ra_f"
    else:
        run = Decimal("0")
        formula = "tiempo capturado manualmente"
    setup, run = apply_time_overrides(ctx, p, path, Decimal("0"), run, inputs, notes)
    line = priced_hours(ctx, rate_key=str(r.get("weld_finishing.rate_key")), category="weld_finishing", comp=comp,
                        process_id=p.process_id, path=path, h_one=setup, h_unit_piece=run, mult=mult, formula=formula,
                        inputs=inputs, rule_refs=[r.rule_ref("weld_finishing")], description=label, notes=notes)
    _add_consumables_pct(line, ctx, "weld_finishing.consumables_pct_of_labor")

"""Corte láser, doblez y rolado."""

from __future__ import annotations

from decimal import Decimal

from ..cost_engine.context import CostContext
from ..schemas.common import Impact, Severity
from ..schemas.manufacturing import Bending, Component, LaserCutting, Rolling
from .common import apply_time_overrides, max_dim, priced_hours

SIXTY = Decimal("60")
K = Decimal("1000")


def cost_laser(ctx: CostContext, comp: Component, p: LaserCutting, path: str, mult: Decimal) -> None:
    r = ctx.rules
    inputs: dict = {}
    notes: list[str] = []
    cid = comp.component_id
    m = comp.material
    thickness = ctx.val(m.thickness, "mm") if m else None
    if not p.cut_length.known or thickness is None:
        if not p.run_time_override.known:
            ctx.missing(category="laser_cutting", description=f"{cid}: corte láser", component_id=cid, process_id=p.process_id,
                        reason="falta longitud de corte o espesor", severity=Severity.HIGH, field_path=f"{path}.cut_length")
            return
    setup = r.get("laser.setup_time_hr")
    load = r.get("laser.loading_time_hr")
    handling = r.get("laser.handling_time_hr")
    inputs.update(setup_time=ctx.rule_input("laser.setup_time_hr", setup, "hr"),
                  loading_time=ctx.rule_input("laser.loading_time_hr", load, "hr"),
                  handling_time=ctx.rule_input("laser.handling_time_hr", handling, "hr"))
    run = load + handling
    formula = "run = loading + handling"
    if p.cut_length.known and thickness is not None:
        cut = ctx.val(p.cut_length, "mm")
        speed, band = r.band("laser.speed_mm_min", thickness, "max_thickness", "speed")
        grade = str(m.grade.value) if m and m.grade.known else None
        mf = r.lookup("laser.material_factor", grade, Decimal("1")) if grade else Decimal("1")
        pierces = ctx.val(p.pierce_count) if p.pierce_count.known else Decimal("0")
        if not p.pierce_count.known:
            notes.append("pierce_count desconocido: 0 perforaciones consideradas")
        pierce_s = r.get("laser.pierce_time_s")
        cut_hr = cut / speed / SIXTY * mf
        pierce_hr = pierces * pierce_s / Decimal("3600")
        run = run + cut_hr + pierce_hr
        inputs.update(cut_length=ctx.ti(p.cut_length, f"{path}.cut_length"), thickness=ctx.ti(m.thickness, "material.thickness"),
                      speed=ctx.rule_input(band, speed, "mm/min"), material_factor=ctx.rule_input("laser.material_factor", mf, key=grade),
                      pierce_count=ctx.derived(pierces, "ea", "pierce_count"), pierce_time=ctx.rule_input("laser.pierce_time_s", pierce_s, "s"))
        formula = "run = loading + handling + cut_length / speed / 60 × material_factor + pierces × pierce_s / 3600"
    setup, run = apply_time_overrides(ctx, p, path, setup, run, inputs, notes)
    priced_hours(ctx, rate_key=str(r.get("laser.rate_key")), category="laser_cutting", comp=comp, process_id=p.process_id,
                 path=path, h_one=setup, h_unit_piece=run, mult=mult, formula=formula, inputs=inputs,
                 rule_refs=[r.rule_ref("laser")], description=f"{cid}: corte láser", notes=notes)


def cost_bending(ctx: CostContext, comp: Component, p: Bending, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    inputs: dict = {}
    notes: list[str] = []
    if not p.number_of_bends.known and not p.run_time_override.known:
        ctx.missing(category="bending", description=f"{cid}: doblez", component_id=cid, process_id=p.process_id,
                    reason="número de dobleces desconocido", severity=Severity.HIGH, field_path=f"{path}.number_of_bends")
        return
    setup_each = r.get("bending.setup_time_hr")
    tool_change = r.get("bending.tool_change_hr")
    setup = setup_each * p.setup_count + tool_change * p.tool_changes
    inputs.update(setup_time=ctx.rule_input("bending.setup_time_hr", setup_each, "hr"), setup_count=ctx.derived(p.setup_count, "ea", "captured"),
                  tool_change=ctx.rule_input("bending.tool_change_hr", tool_change, "hr"), tool_changes=ctx.derived(p.tool_changes, "ea", "captured"))
    run = Decimal("0")
    formula = "setup = setup_hr × setups + tool_change_hr × changes"
    if p.number_of_bends.known:
        bends = ctx.val(p.number_of_bends)
        tpb = r.get("bending.time_per_bend_hr")
        thickness = ctx.val(comp.material.thickness, "mm") if comp.material else None
        if thickness is None:
            tf, tband = Decimal("1"), "NOT APPLIED (espesor desconocido)"
            ctx.review(severity=Severity.MEDIUM, category="bending", impact=Impact.MEDIUM,
                       field_path=f"{path}", description=f"{cid}: espesor desconocido, factor de espesor de doblez no aplicado",
                       action="Confirmar espesor")
        else:
            tf, tband = r.band("bending.thickness_factor", thickness, "max_thickness")
        md = max_dim(comp, ctx)
        if md is None:
            sf, sband = Decimal("1"), "NOT APPLIED (bounding box desconocido)"
        else:
            sf, sband = r.band("bending.size_factor", md, "max_dim")
        hf = r.lookup("bending.handling_complexity_factor", p.handling_complexity)
        handling = r.get("bending.handling_time_hr")
        run = bends * tpb * tf * sf * hf + handling
        inputs.update(number_of_bends=ctx.ti(p.number_of_bends, f"{path}.number_of_bends"),
                      time_per_bend=ctx.rule_input("bending.time_per_bend_hr", tpb, "hr"),
                      thickness_factor=ctx.rule_input(tband, tf) if "NOT" not in tband else ctx.derived(1, "factor", tband),
                      size_factor=ctx.rule_input(sband, sf) if "NOT" not in sband else ctx.derived(1, "factor", sband),
                      handling_factor=ctx.rule_input("bending.handling_complexity_factor", hf, key=p.handling_complexity),
                      handling_time=ctx.rule_input("bending.handling_time_hr", handling, "hr"))
        formula += "; run = bends × time_per_bend × thickness_f × size_f × handling_f + handling_hr"
    setup, run = apply_time_overrides(ctx, p, path, setup, run, inputs, notes)
    priced_hours(ctx, rate_key=str(r.get("bending.rate_key")), category="bending", comp=comp, process_id=p.process_id,
                 path=path, h_one=setup, h_unit_piece=run, mult=mult, formula=formula, inputs=inputs,
                 rule_refs=[r.rule_ref("bending")], description=f"{cid}: doblez", notes=notes)


def cost_rolling(ctx: CostContext, comp: Component, p: Rolling, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    inputs: dict = {}
    notes: list[str] = []
    if not p.rolled_length.known and not p.run_time_override.known:
        ctx.missing(category="rolling", description=f"{cid}: rolado", component_id=cid, process_id=p.process_id,
                    reason="longitud rolada desconocida", severity=Severity.MEDIUM, field_path=f"{path}.rolled_length")
        return
    setup = r.get("rolling.setup_time_hr")
    run = Decimal("0")
    if p.rolled_length.known:
        L = ctx.val(p.rolled_length, "mm") / K
        tpm = r.get("rolling.time_per_m_hr")
        run = L * tpm
        inputs.update(rolled_length_m=ctx.derived(L, "m", "rolled_length/1000"), time_per_m=ctx.rule_input("rolling.time_per_m_hr", tpm, "hr/m"))
    inputs["setup_time"] = ctx.rule_input("rolling.setup_time_hr", setup, "hr")
    setup, run = apply_time_overrides(ctx, p, path, setup, run, inputs, notes)
    priced_hours(ctx, rate_key=str(r.get("rolling.rate_key")), category="rolling", comp=comp, process_id=p.process_id,
                 path=path, h_one=setup, h_unit_piece=run, mult=mult, formula="run = length_m × time_per_m", inputs=inputs,
                 rule_refs=[r.rule_ref("rolling")], description=f"{cid}: rolado", notes=notes)

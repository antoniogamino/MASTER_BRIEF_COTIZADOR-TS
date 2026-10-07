"""Soldadura: horas = longitud × lados / productividad × Π factores. Consumibles por metro.

Reglas críticas:
  * side unknown -> la junta NO se costea (no se asume one_side ni both_sides) y se genera alerta HIGH.
  * factores opcionales desconocidos -> factor 1.0 + alerta (nunca se inventa el dato).
"""

from __future__ import annotations

from decimal import Decimal

from ..cost_engine.context import CostContext, MissingFxError
from ..schemas.common import Impact, Severity, SourceStatus
from ..schemas.manufacturing import Component, Side, Welding
from ..schemas.results import CostSourceRef, TraceInput
from .common import ONE, ZERO, apply_time_overrides, enum_val, factor, max_dim, priced_hours

K = Decimal("1000")


def cost_welding(ctx: CostContext, comp: Component, p: Welding, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    if not p.joints:
        if p.run_time_override.known:
            inputs: dict = {}
            notes: list[str] = []
            h1, hu = apply_time_overrides(ctx, p, path, ZERO, ZERO, inputs, notes)
            priced_hours(ctx, rate_key=str(r.get("welding.rate_key")), category="welding", comp=comp, process_id=p.process_id,
                         path=path, h_one=h1, h_unit_piece=hu, mult=mult, formula="tiempo capturado manualmente",
                         inputs=inputs, rule_refs=[], description=f"{cid}: soldadura (tiempo manual)", notes=notes)
        else:
            ctx.missing(category="welding", description=f"{cid}: soldadura", component_id=cid, process_id=p.process_id,
                        reason="proceso de soldadura sin juntas definidas", severity=Severity.HIGH, field_path=f"{path}.joints",
                        question=f"Confirmar juntas soldadas de {comp.description} (tipo, longitud, lados).")
        return

    grade = str(comp.material.grade.value) if comp.material and comp.material.grade.known else None
    thickness = ctx.val(comp.material.thickness, "mm") if comp.material else None
    md = max_dim(comp, ctx)
    total_dep_m = ZERO   # metros depositados (para consumibles)
    purge_m = ZERO

    for j_i, j in enumerate(p.joints):
        jp = f"{path}.joints[{j_i}]"
        inputs: dict = {}
        if not j.weld_length.known:
            ctx.missing(category="welding", description=f"{cid}/{j.joint_id}: soldadura", component_id=cid, process_id=p.process_id,
                        reason="longitud de soldadura desconocida", severity=Severity.HIGH, field_path=f"{jp}.weld_length",
                        question=f"Confirmar longitud de cordón de la junta {j.joint_id} en {comp.description}.")
            continue
        side = j.side.value if j.side.known else None
        side = enum_val(side)
        if side in (None, Side.UNKNOWN.value):
            ctx.missing(category="welding", description=f"{cid}/{j.joint_id}: soldadura", component_id=cid, process_id=p.process_id,
                        reason="no se sabe si la soldadura es por uno o ambos lados (no se asume)", severity=Severity.HIGH,
                        field_path=f"{jp}.side",
                        question=f"Confirmar si la junta {j.joint_id} de {comp.description} requiere soldadura continua "
                                 f"por un lado o por ambos lados (interior y exterior).")
            continue
        length_m = ctx.val(j.weld_length, "mm") / K
        sides = r.lookup("welding.side_multiplier", side)
        prod = r.lookup("welding.productivity_m_per_hr", j.process)
        inputs.update(weld_length_m=ctx.derived(length_m, "m", f"{jp}.weld_length/1000 ({j.weld_length.source_status.value})"),
                      side_multiplier=TraceInput(value=str(sides), source=f"{r.rule_ref('welding.side_multiplier')}[{side}] ← {jp}.side ({j.side.source_status.value})"),
                      productivity=ctx.rule_input("welding.productivity_m_per_hr", prod, "m/hr", key=j.process))
        f = ONE
        unk: list[str] = []
        # factores con dato del componente
        mf = r.lookup("welding.material_factor", grade, ONE) if grade else ONE
        inputs["material_factor"] = ctx.rule_input("welding.material_factor", mf, key=grade) if grade else ctx.derived(1, "factor", "NOT APPLIED: grado desconocido")
        f *= mf
        if thickness is not None:
            tf, tb = r.band("welding.thickness_factor", thickness, "max_thickness")
            inputs["thickness_factor"] = ctx.rule_input(tb, tf)
        else:
            tf = ONE
            inputs["thickness_factor"] = ctx.derived(1, "factor", "NOT APPLIED: espesor desconocido")
        f *= tf
        jf = r.lookup("welding.joint_factor", j.joint_type)
        inputs["joint_factor"] = ctx.rule_input("welding.joint_factor", jf, key=j.joint_type)
        f *= jf
        # factores con dato de la junta (unknown -> 1.0 + alerta)
        f *= factor(ctx, j.accessibility, "welding.accessibility_factor", f"{jp}.accessibility", inputs, "accessibility_factor", "welding", "accesibilidad", unk)
        f *= factor(ctx, j.sanitary, "welding.sanitary_factor", f"{jp}.sanitary", inputs, "sanitary_factor", "welding", "requisito sanitario", unk)
        f *= factor(ctx, j.purge_required, "welding.purge_factor", f"{jp}.purge_required", inputs, "purge_factor", "welding", "purga", unk)
        f *= factor(ctx, j.penetration, "welding.penetration_factor", f"{jp}.penetration", inputs, "penetration_factor", "welding", "penetración", unk)
        f *= factor(ctx, j.continuity, "welding.continuity_factor", f"{jp}.continuity", inputs, "continuity_factor", "welding", "continuidad", unk)
        f *= factor(ctx, j.position, "welding.position_factor", f"{jp}.position", inputs, "position_factor", "welding", "posición", unk)
        if unk:
            ctx.review(severity=Severity.MEDIUM, category="welding", impact=Impact.MEDIUM, field_path=jp,
                       description=f"{cid}/{j.joint_id}: sin dato de {', '.join(unk)} — factores no aplicados (costo puede estar subestimado)",
                       action="Confirmar con plano/cliente sólo si aplica (sanitario, penetración completa y purga son los de mayor impacto)")
        small_max = r.get("welding.small_part.max_dim_mm")
        if md is not None and md <= small_max:
            spf = r.get("welding.small_part.factor")
            inputs["small_part_factor"] = ctx.rule_input("welding.small_part.factor", spf)
            f *= spf
        hours = length_m * sides / prod * f
        dep = length_m * sides
        total_dep_m += dep
        if j.purge_required.known and j.purge_required.value:
            purge_m += length_m
        # alerta si se declaró acabado post-soldadura pero no hay proceso de acabado ruteado
        if (j.post_weld_grinding.known and j.post_weld_grinding.value) or (j.post_weld_polishing.known and j.post_weld_polishing.value):
            if not any(getattr(pp, "process_type", "") == "weld_finishing" for pp in comp.processes):
                ctx.review(severity=Severity.HIGH, category="weld_finishing", impact=Impact.HIGH, field_path=f"{jp}",
                           description=f"{cid}/{j.joint_id}: requiere acabado post-soldadura pero no hay proceso weld_finishing en la ruta",
                           action="Agregar proceso de acabado de soldadura")
        notes: list[str] = []
        h1, hu = ZERO, hours
        if len(p.joints) == 1:
            h1, hu = apply_time_overrides(ctx, p, path, h1, hu, inputs, notes)
        priced_hours(ctx, rate_key=str(r.get("welding.rate_key")), category="welding", comp=comp, process_id=p.process_id,
                     path=jp, h_one=h1, h_unit_piece=hu, mult=mult,
                     formula="hours = length_m × side_mult / productivity × Π(factors)", inputs=inputs,
                     rule_refs=[r.rule_ref("welding")], description=f"{cid}/{j.joint_id}: soldadura {j.process} {j.joint_type}",
                     notes=notes, quantities={"deposited_m": str(dep), "combined_factor": str(f)})

    if total_dep_m > 0:
        _consumables(ctx, comp, p, path, mult, total_dep_m, purge_m)


def _consumables(ctx: CostContext, comp: Component, p: Welding, path: str, mult: Decimal, dep_m: Decimal, purge_m: Decimal) -> None:
    r = ctx.rules
    per_m = r.get("welding.consumption_per_m")
    keys = r.get("welding.consumable_keys")
    inputs: dict = {"deposited_m": ctx.derived(dep_m, "m", "Σ length × sides"), "purge_m": ctx.derived(purge_m, "m", "Σ length with purge")}
    total = ZERO
    srcs: list[CostSourceRef] = []
    missing: list[str] = []
    qty_map = {k: Decimal(v) * dep_m for k, v in per_m.items()}
    qty_map["argon_l"] = qty_map.get("argon_l", ZERO) + r.get("welding.purge_argon_l_per_m") * purge_m
    for ck, qty in qty_map.items():
        item_key = keys.get(ck)
        it = ctx.master.item("consumables", item_key) if item_key else None
        inputs[f"{ck}_qty"] = ctx.rule_input(f"welding.consumption_per_m", per_m.get(ck), key=ck)
        if it is None:
            missing.append(item_key or ck)
            continue
        try:
            unit_p, fx = ctx.to_project(it.unit_cost, it.currency)
        except MissingFxError:
            missing.append(item_key)
            continue
        total += qty * unit_p
        srcs.append(CostSourceRef(kind="consumable", key=it.item_key, supplier=it.supplier, price_date=it.price_date,
                                  original_value=str(it.unit_cost), original_currency=it.currency, is_sample=it.is_sample))
    if missing:
        ctx.missing(category="welding_consumables", description=f"{comp.component_id}: consumibles de soldadura",
                    component_id=comp.component_id, process_id=p.process_id,
                    reason=f"precio faltante para: {', '.join(missing)}", severity=Severity.LOW, impact=Impact.LOW)
        return
    ctx.add(category="welding_consumables", component_id=comp.component_id, process_id=p.process_id,
            description=f"{comp.component_id}: consumibles soldadura (argón, aporte, tungsteno)",
            per_unit=total * mult, quantities={k: str(v) for k, v in qty_map.items()},
            formula="Σ (consumo_por_m × m depositados [+ purga]) × precio unitario × multiplier",
            inputs=inputs, sources=srcs, rule_refs=[r.rule_ref("welding.consumption_per_m")])

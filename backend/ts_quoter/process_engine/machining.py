"""Maquinado, procesos genéricos por tiempo y subcontratación."""

from __future__ import annotations

from decimal import Decimal

from ..cost_engine.context import CostContext, MissingFxError
from ..schemas.common import Impact, Severity
from ..schemas.manufacturing import Component, GenericProcess, Machining, Outsourcing
from ..schemas.results import CostSourceRef
from .common import apply_time_overrides, priced_hours, tightest_tolerance

SIXTY = Decimal("60")
HUNDRED = Decimal("100")


def tolerance_factor(ctx: CostContext, comp: Component, inputs: dict) -> Decimal:
    tol = tightest_tolerance(comp, ctx)
    if tol is None:
        inputs["tolerance_factor"] = ctx.derived(1, "factor", "sin tolerancias capturadas")
        return Decimal("1")
    for i, row in enumerate(ctx.rules.get("machining.tolerance_factor")):
        if tol > row["min_tol"]:
            inputs["tolerance_factor"] = ctx.rule_input(f"machining.tolerance_factor[{i}]", row["factor"])
            inputs["tightest_tolerance"] = ctx.derived(tol, "mm", f"min(±tol) → {row['category']}")
            return row["factor"]
    last = ctx.rules.get("machining.tolerance_factor")[-1]
    inputs["tolerance_factor"] = ctx.rule_input("machining.tolerance_factor[-1]", last["factor"])
    return last["factor"]


def cost_machining(ctx: CostContext, comp: Component, p: Machining, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    inputs: dict = {}
    notes: list[str] = []
    label = f"{cid}: maquinado {p.machine_type}"
    if not p.cycle_time.known and not p.run_time_override.known:
        ctx.missing(category="machining", description=label, component_id=cid, process_id=p.process_id,
                    reason="tiempo de ciclo desconocido", severity=Severity.HIGH, field_path=f"{path}.cycle_time",
                    action="Capturar tiempo de ciclo estimado por programador CNC")
        return
    if not p.setup_time.known:
        ctx.review(severity=Severity.MEDIUM, category="machining", impact=Impact.MEDIUM, field_path=f"{path}.setup_time",
                   description=f"{label}: setup desconocido, considerado 0 h (subestimación probable)", action="Capturar setup")
    setup = ctx.val(p.setup_time, "hr") if p.setup_time.known else Decimal("0")
    cycle = ctx.val(p.cycle_time, "hr") if p.cycle_time.known else Decimal("0")
    tf = tolerance_factor(ctx, comp, inputs)
    run = cycle * tf
    if p.setup_time.known:
        inputs["setup_time"] = ctx.ti(p.setup_time, f"{path}.setup_time")
    if p.cycle_time.known:
        inputs["cycle_time"] = ctx.ti(p.cycle_time, f"{path}.cycle_time")
    setup = setup * tf
    if p.special_fixture:
        ctx.review(severity=Severity.MEDIUM, category="machining", impact=Impact.MEDIUM, field_path=path,
                   description=f"{label}: requiere fixture especial; verificar que esté costeado en engineering.fixtures",
                   action="Agregar fixture con costo y política de amortización")
    setup, run = apply_time_overrides(ctx, p, path, setup, run, inputs, notes)
    rate_key = r.lookup("machining.rate_keys", p.machine_type)
    line = priced_hours(ctx, rate_key=str(rate_key), category="machining", comp=comp, process_id=p.process_id, path=path,
                        h_one=setup, h_unit_piece=run, mult=mult,
                        formula="setup = setup_hr × tol_f ; run = cycle_hr × tol_f", inputs=inputs,
                        rule_refs=[r.rule_ref("machining")], description=label, notes=notes)
    if line is not None and p.tooling_cost.known:
        line.one_time += ctx.val(p.tooling_cost)
        line.inputs["tooling_cost"] = ctx.ti(p.tooling_cost, f"{path}.tooling_cost")
        line.formula += " ; + tooling_cost (una vez)"


def cost_generic(ctx: CostContext, comp: Component, p: GenericProcess, path: str, mult: Decimal) -> None:
    r = ctx.rules
    cid = comp.component_id
    label = f"{cid}: {p.process_type}"
    if p.process_type == "unknown":
        ctx.missing(category="generic_process", description=label + (f" — {p.description}" if p.description else ""),
                    component_id=cid, process_id=p.process_id, reason="proceso identificado pero de tipo desconocido",
                    severity=Severity.HIGH, field_path=f"{path}.process_type", action="Identificar el proceso y su tiempo")
        return
    inputs: dict = {}
    notes: list[str] = []
    parts_known = [t for t in (p.run_time, p.setup_time) if t.known]
    if not parts_known and not p.run_time_override.known and not p.setup_time_override.known:
        ctx.missing(category="generic_process", description=label, component_id=cid, process_id=p.process_id,
                    reason="tiempos de setup y ejecución desconocidos", severity=Severity.MEDIUM, impact=Impact.MEDIUM,
                    field_path=f"{path}.run_time")
        return
    setup = ctx.val(p.setup_time, "hr") if p.setup_time.known else Decimal("0")
    run = Decimal("0")
    for name in ("run_time", "handling_time", "inspection_time"):
        t = getattr(p, name)
        if t.known:
            run += ctx.val(t, "hr")
            inputs[name] = ctx.ti(t, f"{path}.{name}")
    if p.setup_time.known:
        inputs["setup_time"] = ctx.ti(p.setup_time, f"{path}.setup_time")
    setup, run = apply_time_overrides(ctx, p, path, setup, run, inputs, notes)
    rate_key = r.lookup("generic_process_rate_keys", p.process_type, p.process_type)
    priced_hours(ctx, rate_key=str(rate_key), category="generic_process", comp=comp, process_id=p.process_id, path=path,
                 h_one=setup, h_unit_piece=run, mult=mult, formula="setup ; run = run + handling + inspection",
                 inputs=inputs, rule_refs=[r.rule_ref("generic_process_rate_keys")], description=label, notes=notes)


def cost_outsourcing(ctx: CostContext, comp: Component, p: Outsourcing, path: str, mult: Decimal) -> None:
    """Servicio subcontratado: cotización del proveedor + markup de política + logística. No es proceso interno."""
    cid = comp.component_id
    label = f"{cid}: subcontrato {p.outsourced_process}"
    if not p.cost_per_piece.known:
        ctx.missing(category="outsourcing", description=label, component_id=cid, process_id=p.process_id,
                    reason="sin cotización de proveedor (Missing Cost)", severity=Severity.HIGH, field_path=f"{path}.cost_per_piece",
                    action=f"Solicitar cotización a proveedor de {p.outsourced_process}")
        return
    ccy = p.currency or ctx.currency
    try:
        per, fx = ctx.to_project(ctx.val(p.cost_per_piece), ccy)
        one = ctx.to_project(ctx.val(p.one_time_cost), ccy)[0] if p.one_time_cost.known else Decimal("0")
        logi = ctx.to_project(ctx.val(p.logistics_cost), ccy)[0] if p.logistics_cost.known else Decimal("0")
    except MissingFxError as e:
        ctx.missing(category="outsourcing", description=label, component_id=cid, process_id=p.process_id, reason=str(e))
        return
    mk = ctx.rules.get("outsourcing.markup_pct")
    factor = 1 + mk / HUNDRED
    srcs = [CostSourceRef(kind="supplier_quote", key=p.supplier_quote_ref or p.process_id, supplier=p.supplier,
                          reference=p.supplier_quote_ref, price_date=p.quote_date, original_value=str(p.cost_per_piece.value),
                          original_currency=ccy)]
    if (s := ctx.fx_source(fx)):
        srcs.append(s)
    if not p.logistics_cost.known:
        ctx.review(severity=Severity.LOW, category="outsourcing", impact=Impact.LOW, field_path=f"{path}.logistics_cost",
                   description=f"{label}: logística del subcontrato desconocida (no costeada)", action="Confirmar flete ida/vuelta")
    ctx.add(category="outsourcing", component_id=cid, process_id=p.process_id, description=label,
            one_time=(one + logi) * factor, per_unit=per * mult * factor,
            formula="(one_time + logistics + cost_per_piece × qty × multiplier) × (1 + markup%)",
            inputs={"cost_per_piece": ctx.ti(p.cost_per_piece, f"{path}.cost_per_piece"),
                    "markup_pct": ctx.rule_input("outsourcing.markup_pct", mk, "%"),
                    "component_multiplier": ctx.derived(mult, "pcs/unit", "Π quantity_per_parent")},
            sources=srcs, rule_refs=[ctx.rules.rule_ref("outsourcing")])

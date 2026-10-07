"""Empaque, calidad, logística, componentes comprados e ingeniería/NRE."""

from __future__ import annotations

from decimal import Decimal

from ..cost_engine.context import CostContext, MissingFxError
from ..schemas.common import Impact, RequirementStatus, Severity
from ..schemas.manufacturing import Component
from ..schemas.results import CostSourceRef, TraceInput

ZERO = Decimal("0")
MM3_TO_M3 = Decimal("1E-9")


def _priced_item(ctx: CostContext, table: str, key: str):
    it = ctx.master.item(table, key)
    if it is None:
        return None, None, None
    try:
        val, fx = ctx.to_project(it.unit_cost, it.currency)
    except MissingFxError:
        return it, None, None
    src = CostSourceRef(kind=table.rstrip("s") if table != "quality" else "quality", key=key, supplier=it.supplier,
                        price_date=it.price_date, original_value=str(it.unit_cost), original_currency=it.currency,
                        is_sample=it.is_sample)
    return it, val, src


def _status(st: RequirementStatus) -> str:
    return getattr(st, "value", st)


def cost_quality(ctx: CostContext) -> None:
    for i, q in enumerate(ctx.job.quality_requirements):
        path = f"quality_requirements[{i}]"
        st = _status(q.status)
        if st == "not_required":
            continue
        if st == "unknown":
            ctx.review(severity=Severity.MEDIUM, category="quality", impact=Impact.MEDIUM, field_path=path,
                       description=f"Requisito de calidad '{q.item_key}' sin confirmar (no costeado)",
                       action="Confirmar con cliente si aplica", question=f"Confirmar si se requiere {q.item_key.replace('_', ' ')}.")
            continue
        it, val, src = _priced_item(ctx, "quality", q.item_key)
        if val is None:
            ctx.missing(category="quality", description=f"calidad: {q.item_key}", reason="costo no disponible en Cost Master",
                        severity=Severity.MEDIUM, impact=Impact.MEDIUM, field_path=path)
            continue
        qty = Decimal(str(q.quantity))
        one, per = (val * qty, ZERO) if q.basis == "per_lot" else (ZERO, val * qty)
        notes = ["requisito INFERIDO: confirmar"] if st == "inferred" else []
        if st == "inferred":
            ctx.review(severity=Severity.LOW, category="quality", impact=Impact.LOW, field_path=path,
                       description=f"'{q.item_key}' costeado por inferencia", action="Confirmar requisito")
        ctx.add(category="quality", description=f"calidad: {q.item_key} ({q.basis})", one_time=one, per_unit=per,
                formula=f"unit_cost × quantity ({q.basis})",
                inputs={"unit_cost": TraceInput(value=str(val), unit=ctx.currency, source=f"cost_master:quality[{q.item_key}]"),
                        "quantity": TraceInput(value=str(qty), source=f"mcj:{path}.quantity ({st})")},
                sources=[src], notes=notes)


def cost_buy(ctx: CostContext, comp: Component, path: str, mult: Decimal) -> None:
    b = comp.buy
    cid = comp.component_id
    if b is None or not b.unit_cost.known:
        ctx.missing(category="buy_component", description=f"{cid}: {comp.description} (comprado)",
                    reason="Missing Cost: sin precio de componente comercial", component_id=cid,
                    severity=Severity.HIGH, field_path=f"{path}.buy.unit_cost",
                    action="Solicitar cotización al proveedor/fabricante")
        return
    ccy = b.currency or ctx.currency
    try:
        val, fx = ctx.to_project(ctx.val(b.unit_cost), ccy)
    except MissingFxError as e:
        ctx.missing(category="buy_component", description=f"{cid}: comprado", reason=str(e), component_id=cid, severity=Severity.CRITICAL)
        return
    srcs = [CostSourceRef(kind="supplier_quote", key=b.part_number or cid, supplier=b.supplier, reference=b.price_source_ref,
                          price_date=b.price_date, original_value=str(b.unit_cost.value), original_currency=ccy)]
    if (s := ctx.fx_source(fx)):
        srcs.append(s)
    if b.price_date:
        from ..money import recency
        age, rec = recency(b.price_date, ctx.as_of, ctx.rules)
        srcs[0].age_days, srcs[0].recency = age, rec
    ctx.add(category="buy_component", component_id=cid, description=f"{cid}: {comp.description} ({b.manufacturer or ''} {b.model or ''})".strip(),
            per_unit=val * mult, formula="unit_cost × multiplier",
            inputs={"unit_cost": ctx.ti(b.unit_cost, f"{path}.buy.unit_cost"),
                    "component_multiplier": ctx.derived(mult, "pcs/unit", "Π quantity_per_parent")},
            sources=srcs)


def cost_packaging(ctx: CostContext) -> None:
    pk = ctx.job.packaging_requirements
    r = ctx.rules
    if not pk.packaging_type.known:
        ctx.review(severity=Severity.LOW, category="packaging", impact=Impact.LOW, field_path="packaging_requirements.packaging_type",
                   description="Tipo de empaque no definido (no costeado)", action="Definir empaque")
    else:
        ptype = pk.packaging_type.value
        if ptype == "wood_crate":
            _crate(ctx)
        elif ptype in ("cardboard", "pallet"):
            key = str(r.get("packaging.cardboard_cost_key" if ptype == "cardboard" else "packaging.pallet_cost_key"))
            it, val, src = _priced_item(ctx, "packaging", key)
            if val is None:
                ctx.missing(category="packaging", description=f"empaque {ptype}", reason=f"'{key}' sin costo", severity=Severity.LOW, impact=Impact.LOW)
            else:
                ctx.add(category="packaging", description=f"empaque {ptype}", per_unit=val / pk.units_per_package,
                        formula="unit_cost / units_per_package (prorrateo por unidad)",
                        inputs={"unit_cost": TraceInput(value=str(val), unit=ctx.currency, source=f"cost_master:packaging[{key}]")},
                        sources=[src])
        elif ptype in ("custom", "customer_specified"):
            ctx.review(severity=Severity.MEDIUM, category="packaging", impact=Impact.MEDIUM, field_path="packaging_requirements",
                       description=f"Empaque '{ptype}' requiere costeo manual", action="Agregar costo de empaque especial")
    for i, it_req in enumerate(pk.items):
        path = f"packaging_requirements.items[{i}]"
        st = _status(it_req.status)
        if st == "not_required":
            continue
        if st == "unknown":
            sev = Severity.MEDIUM if (ctx.job.project.export.known and ctx.job.project.export.value) else Severity.LOW
            ctx.review(severity=sev, category="packaging", impact=Impact.LOW, field_path=path,
                       description=f"Elemento de empaque '{it_req.item_key}' sin confirmar", action="Confirmar requisito")
            continue
        it, val, src = _priced_item(ctx, "packaging", it_req.item_key)
        if val is None:
            ctx.missing(category="packaging", description=f"empaque: {it_req.item_key}", reason="costo no disponible",
                        severity=Severity.LOW, impact=Impact.LOW, field_path=path)
            continue
        qty = Decimal(str(it_req.quantity))
        if it_req.basis == "per_piece":
            one, per = ZERO, val * qty
        elif it_req.basis == "per_package":
            one, per = ZERO, val * qty / pk.units_per_package
        else:
            one, per = val * qty, ZERO
        ctx.add(category="packaging", description=f"empaque: {it_req.item_key}", one_time=one, per_unit=per,
                formula=f"unit_cost × quantity ({it_req.basis})",
                inputs={"unit_cost": TraceInput(value=str(val), unit=ctx.currency, source=f"cost_master:packaging[{it_req.item_key}]")},
                sources=[src], notes=["inferido"] if st == "inferred" else [])


def _crate(ctx: CostContext) -> None:
    """Caja de madera: volumen exterior desde bounding box del producto + holgura (por paquete)."""
    r = ctx.rules
    pk = ctx.job.packaging_requirements
    roots = [c for c in ctx.job.active_components() if c.parent_component_id is None]
    bb = roots[0].geometry.bounding_box if len(roots) == 1 else None
    if bb is None or not all(t.known for t in (bb.length, bb.width, bb.height)):
        ctx.missing(category="packaging", description="caja de madera", reason="bounding box del producto desconocido o múltiples raíces",
                    severity=Severity.MEDIUM, impact=Impact.MEDIUM, field_path="components[root].geometry.bounding_box")
        return
    clearance = Decimal(str(pk.clearance_mm)) if pk.clearance_mm is not None else r.get("packaging.default_clearance_mm")
    dims = [ctx.val(t, "mm") + 2 * clearance for t in (bb.length, bb.width, bb.height)]
    vol = dims[0] * dims[1] * dims[2] * MM3_TO_M3
    key = str(r.get("packaging.crate_cost_key"))
    it, val, src = _priced_item(ctx, "packaging", key)
    if val is None:
        ctx.missing(category="packaging", description="caja de madera", reason=f"'{key}' sin costo", severity=Severity.MEDIUM, impact=Impact.MEDIUM)
        return
    per_pkg = vol * val
    if pk.units_per_package > 1:
        ctx.review(severity=Severity.LOW, category="packaging", impact=Impact.LOW, field_path="packaging_requirements.units_per_package",
                   description="Caja con varias piezas: volumen calculado para una pieza; verificar arreglo", action="Revisar dimensiones de caja")
    ctx.add(category="packaging", description="caja de madera (por volumen)",
            per_unit=per_pkg / pk.units_per_package,
            quantities={"crate_dims_mm": "×".join(str(d) for d in dims), "crate_volume_m3": str(vol)},
            formula="(L+2c)(W+2c)(H+2c) × 1e-9 × cost_per_m3 / units_per_package",
            inputs={"clearance": ctx.rule_input("packaging.default_clearance_mm", clearance, "mm") if pk.clearance_mm is None else TraceInput(value=str(clearance), unit="mm", source="mcj:packaging_requirements.clearance_mm"),
                    "cost_per_m3": TraceInput(value=str(val), unit=f"{ctx.currency}/m3", source=f"cost_master:packaging[{key}]")},
            sources=[src], rule_refs=[r.rule_ref("packaging")])


def cost_logistics(ctx: CostContext) -> None:
    export = ctx.job.project.export
    for i, li in enumerate(ctx.job.logistics):
        path = f"logistics[{i}]"
        st = _status(li.status)
        if st == "not_required":
            continue
        if st == "unknown" or not li.cost.known:
            if st != "unknown" or (export.known and export.value):
                ctx.missing(category="logistics", description=f"logística: {li.item_key}",
                            reason="requisito o costo desconocido", severity=Severity.MEDIUM, impact=Impact.MEDIUM, field_path=path)
            continue
        try:
            val, fx = ctx.to_project(ctx.val(li.cost), li.currency or ctx.currency)
        except MissingFxError as e:
            ctx.missing(category="logistics", description=f"logística: {li.item_key}", reason=str(e))
            continue
        srcs = [CostSourceRef(kind="logistics", key=li.item_key, reference=li.source_ref, original_value=str(li.cost.value),
                              original_currency=li.currency or ctx.currency)]
        if (s := ctx.fx_source(fx)):
            srcs.append(s)
        ctx.add(category="logistics", description=f"logística: {li.item_key}", one_time=val, formula="costo por lote",
                inputs={"cost": ctx.ti(li.cost, f"{path}.cost")}, sources=srcs)


def cost_engineering(ctx: CostContext) -> None:
    e = ctx.job.engineering
    r = ctx.rules
    fields = ["engineering_hours", "cad_hours", "programming_hours", "manufacturing_planning_hours"]
    known = [(f, getattr(e, f)) for f in fields if getattr(e, f).known]
    if not known:
        ctx.review(severity=Severity.MEDIUM, category="engineering", impact=Impact.MEDIUM, field_path="engineering",
                   description="Horas de ingeniería/CAD/programación no capturadas (no se asume cero)",
                   action="Capturar horas de ingeniería, aunque sea 0 explícito")
    else:
        hours = sum((ctx.val(t, "hr") for _, t in known), Decimal("0"))
        rate_key = str(r.get("engineering.rate_key"))
        rate = ctx.master.rate(rate_key)
        if rate is None:
            ctx.missing(category="engineering", description="ingeniería", reason=f"tarifa '{rate_key}' no existe", severity=Severity.MEDIUM)
        else:
            hr, fx = ctx.to_project(rate.hourly_rate, rate.currency)
            ctx.add(category="engineering", description="ingeniería / CAD / programación / planeación (NRE)",
                    one_time=hours * hr, hours_one_time=hours, formula="Σ horas × tarifa ingeniería",
                    inputs={**{f: ctx.ti(t, f"engineering.{f}") for f, t in known},
                            "hourly_rate": TraceInput(value=str(hr), unit=f"{ctx.currency}/hr", source=f"cost_master:process_rates[{rate_key}]")},
                    sources=[CostSourceRef(kind="process_rate", key=rate_key, original_value=str(rate.hourly_rate),
                                           original_currency=rate.currency, is_sample=rate.is_sample)])
    for i, fx_ in enumerate(e.fixtures):
        path = f"engineering.fixtures[{i}]"
        if not fx_.fixture_cost.known:
            ctx.missing(category="fixture", description=f"fixture {fx_.fixture_id}", reason="costo de fixture desconocido",
                        severity=Severity.MEDIUM, impact=Impact.MEDIUM, field_path=f"{path}.fixture_cost")
            continue
        val, _ = ctx.to_project(ctx.val(fx_.fixture_cost), fx_.currency or ctx.currency)
        if fx_.reusable and fx_.amortization_quantity:
            per = val / Decimal(fx_.amortization_quantity)
            ctx.add(category="fixture", description=f"fixture {fx_.fixture_id} (reusable, amortizado en {fx_.amortization_quantity})",
                    per_unit=per, formula="fixture_cost / amortization_quantity",
                    inputs={"fixture_cost": ctx.ti(fx_.fixture_cost, f"{path}.fixture_cost")})
        else:
            ctx.add(category="fixture", description=f"fixture {fx_.fixture_id} (NRE)", one_time=val, formula="fixture_cost (una vez)",
                    inputs={"fixture_cost": ctx.ti(fx_.fixture_cost, f"{path}.fixture_cost")})

"""Material: peso neto -> consumido -> comprado, selección de precio por jerarquía A–E y costo."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..cost_engine.context import CostContext, MissingFxError
from ..money import recency
from ..schemas.common import Impact, Severity, SourceStatus, Tracked
from ..schemas.cost_master import LEVEL_RANK, MaterialPrice
from ..schemas.manufacturing import Component, MaterialForm
from ..schemas.results import CostSourceRef, TraceInput
from .normalize import normalize_grade

PI = Decimal("3.14159265358979323846")
MM3_TO_M3 = Decimal("1E-9")
HUNDRED = Decimal("100")


def _pct(ctx: CostContext, tracked: Tracked, rule_path: str, path: str, inputs: dict, name: str,
         form_key: Optional[str] = None) -> Decimal:
    """Usa el valor capturado o el default de regla (registrado como 'defaulted' en la traza)."""
    if tracked.known:
        inputs[name] = ctx.ti(tracked, path)
        return tracked.num()  # type: ignore[return-value]
    val = ctx.rules.get(rule_path)
    if isinstance(val, dict):
        val = val.get(form_key, val.get("other"))
    inputs[name] = TraceInput(value=str(val), unit="%", source=f"defaulted by {ctx.rules.rule_ref(rule_path)}" + (f"[{form_key}]" if form_key else ""))
    return Decimal(val)


def net_weight_kg(ctx: CostContext, comp: Component, path: str, inputs: dict) -> tuple[Optional[Decimal], str, Optional[str]]:
    """Devuelve (peso_neto_kg, fórmula, motivo_si_falta)."""
    m = comp.material
    assert m is not None
    if m.net_weight.known:
        inputs["net_weight"] = ctx.ti(m.net_weight, f"{path}.material.net_weight")
        return ctx.val(m.net_weight, "kg"), "net_weight (capturado)", None

    grade = m.grade.value
    density = ctx.rules.lookup("material.density_kg_m3", grade, None) if grade else None
    if density is None:
        return None, "", f"sin densidad para grado '{grade}' en reglas"
    inputs["density"] = ctx.rule_input("material.density_kg_m3", density, "kg/m3", key=grade)
    form = m.form.value
    g = comp.geometry

    def need(t: Tracked, p: str, name: str) -> Optional[Decimal]:
        if not t.known:
            return None
        inputs[name] = ctx.ti(t, p)
        return ctx.val(t, "mm")

    if form in (MaterialForm.SHEET, MaterialForm.PLATE, MaterialForm.FLAT_BAR):
        L = need(g.blank_length if form != MaterialForm.FLAT_BAR else g.cut_length, f"{path}.geometry.{'blank_length' if form != MaterialForm.FLAT_BAR else 'cut_length'}", "length")
        W = need(g.blank_width, f"{path}.geometry.blank_width", "width")
        t = need(m.thickness, f"{path}.material.thickness", "thickness")
        if None in (L, W, t):
            return None, "", "faltan dimensiones de desarrollo (largo/ancho/espesor)"
        return L * W * t * MM3_TO_M3 * density, "L × W × t × 1e-9 × ρ", None  # type: ignore[operator]

    if form == MaterialForm.ROUND_BAR:
        D = need(m.outside_diameter, f"{path}.material.outside_diameter", "outside_diameter")
        L = need(g.cut_length, f"{path}.geometry.cut_length", "length")
        if None in (D, L):
            return None, "", "faltan diámetro o longitud de corte"
        return PI / 4 * D * D * L * MM3_TO_M3 * density, "π/4 × D² × L × 1e-9 × ρ", None  # type: ignore[operator]

    if form in (MaterialForm.TUBE, MaterialForm.SANITARY_TUBE, MaterialForm.PIPE):
        D = need(m.outside_diameter, f"{path}.material.outside_diameter", "outside_diameter")
        L = need(g.cut_length, f"{path}.geometry.cut_length", "length")
        d = need(m.inside_diameter, f"{path}.material.inside_diameter", "inside_diameter")
        if d is None and m.wall_thickness.known and D is not None:
            w = need(m.wall_thickness, f"{path}.material.wall_thickness", "wall_thickness")
            d = D - 2 * w  # type: ignore[operator]
            inputs["inside_diameter"] = ctx.derived(d, "mm", "OD − 2 × wall")
        if None in (D, L, d):
            return None, "", "faltan OD, ID/pared o longitud"
        return PI / 4 * (D * D - d * d) * L * MM3_TO_M3 * density, "π/4 × (OD² − ID²) × L × 1e-9 × ρ", None  # type: ignore[operator]

    return None, "", f"forma '{form}' requiere net_weight capturado (sin fórmula paramétrica en MVP)"


def select_price(ctx: CostContext, grade: str, form: str, thickness: Optional[Decimal]) -> tuple[Optional[MaterialPrice], int]:
    """Jerarquía obligatoria: menor nivel (A mejor) y luego más reciente. NUNCA el más barato."""
    cands = []
    for p in ctx.master.materials:
        if p.grade != grade or p.form != form:
            continue
        if p.thickness_min_mm is not None or p.thickness_max_mm is not None:
            if thickness is None:
                continue
            if p.thickness_min_mm is not None and thickness < p.thickness_min_mm:
                continue
            if p.thickness_max_mm is not None and thickness > p.thickness_max_mm:
                continue
        if p.price_date > ctx.as_of:
            continue  # precio "del futuro" respecto a la fecha de cálculo: reproducibilidad
        cands.append(p)
    cands.sort(key=lambda p: (LEVEL_RANK[p.source_level], -p.price_date.toordinal(), p.price_id))
    return (cands[0] if cands else None), len(cands)


def cost_material(ctx: CostContext, comp: Component, path: str, mult: Decimal) -> None:
    m = comp.material
    cid = comp.component_id
    if m is None:
        ctx.missing(category="material", description=f"{cid}: material", reason="componente MAKE sin material",
                    component_id=cid, severity=Severity.CRITICAL, field_path=f"{path}.material",
                    question=f"Confirmar material (grado y forma) de {comp.description}.")
        return

    # ---- grado: normalización sin destruir raw
    if m.grade.source_status == SourceStatus.CONFLICTING:
        ctx.missing(category="material", description=f"{cid}: material", reason="grado de material en conflicto entre fuentes",
                    component_id=cid, severity=Severity.CRITICAL, field_path=f"{path}.material.grade",
                    question=f"Confirmar el grado de material de {comp.description}: las fuentes indican valores distintos.")
        return
    if not m.grade.known:
        ctx.missing(category="material", description=f"{cid}: material", reason="grado de material desconocido (no se asume 304)",
                    component_id=cid, severity=Severity.CRITICAL, field_path=f"{path}.material.grade",
                    question=f"Confirmar grado de acero inoxidable de {comp.description} (304, 304L, 316, 316L).")
        return
    grade = normalize_grade(str(m.grade.value), ctx.rules)
    if grade is None:
        ctx.missing(category="material", description=f"{cid}: material", reason=f"grado '{m.grade.value}' sin alias conocido",
                    component_id=cid, severity=Severity.HIGH, field_path=f"{path}.material.grade",
                    action="Agregar alias en reglas o corregir el grado")
        return
    if grade != m.grade.value:
        m.grade.raw_value = m.grade.raw_value or str(m.grade.value)
        m.grade.value = grade  # normalized_value; raw_value conservado
    if not m.form.known:
        ctx.missing(category="material", description=f"{cid}: material", reason="forma de material desconocida",
                    component_id=cid, severity=Severity.HIGH, field_path=f"{path}.material.form",
                    question=f"Confirmar si {comp.description} se fabrica de lámina, placa, tubo o barra.")
        return

    inputs: dict = {"grade": ctx.ti(m.grade, f"{path}.material.grade"), "form": ctx.ti(m.form, f"{path}.material.form")}
    net, wformula, reason = net_weight_kg(ctx, comp, path, inputs)
    if net is None:
        ctx.missing(category="material", description=f"{cid}: material {grade}", reason=reason or "peso no calculable",
                    component_id=cid, inputs=inputs, severity=Severity.HIGH, field_path=f"{path}.geometry",
                    question=f"Confirmar dimensiones de desarrollo / longitud de corte de {comp.description}.")
        return

    form = m.form.value.value if hasattr(m.form.value, "value") else str(m.form.value)
    scrap = _pct(ctx, m.process_scrap_pct, "material.defaults.process_scrap_pct", f"{path}.material.process_scrap_pct", inputs, "process_scrap_pct")
    util = _pct(ctx, m.sheet_utilization_pct, "material.defaults.sheet_utilization_pct", f"{path}.material.sheet_utilization_pct", inputs, "utilization_pct", form)
    credit = _pct(ctx, m.remnant_credit_pct, "material.defaults.remnant_credit_pct", f"{path}.material.remnant_credit_pct", inputs, "remnant_credit_pct")
    if util <= 0:
        ctx.missing(category="material", description=f"{cid}: material", reason="aprovechamiento ≤ 0%", component_id=cid)
        return

    consumed = net * (1 + scrap / HUNDRED)
    purchased = consumed / (util / HUNDRED)
    if m.minimum_purchase_quantity_kg:
        moq = Decimal(str(m.minimum_purchase_quantity_kg))
        if purchased * mult < moq:
            ctx.review(severity=Severity.LOW, category="material", impact=Impact.LOW, field_path=f"{path}.material",
                       description=f"{cid}: compra mínima {moq} kg > requerido {purchased * mult:.2f} kg/unidad",
                       action="Evaluar costo de compra mínima vs remanente")

    price, n_cands = select_price(ctx, grade, form, ctx.val(m.thickness, "mm"))
    if price is None:
        ctx.missing(category="material", description=f"{cid}: material {grade} {form}", reason="precio de material no disponible (nivel E: missing)",
                    component_id=cid, inputs=inputs, severity=Severity.CRITICAL, field_path=f"{path}.material",
                    action="Cargar cotización de proveedor o compra histórica en COST_MASTER / HISTORICAL_PURCHASES")
        return

    unit_price = price.price_per_kg * price.adjustment_factor
    try:
        unit_price_p, fx = ctx.to_project(unit_price, price.currency)
    except MissingFxError as e:
        ctx.missing(category="material", description=f"{cid}: material", reason=str(e), component_id=cid, severity=Severity.CRITICAL)
        return
    age, rec = recency(price.price_date, ctx.as_of, ctx.rules)
    if rec in ("stale", "obsolete"):
        ctx.review(severity=Severity.MEDIUM if rec == "stale" else Severity.HIGH, category="cost_data", impact=Impact.MEDIUM,
                   field_path=f"{path}.material", description=f"{cid}: precio {grade} {form} tiene {age} días ({rec})",
                   action="Solicitar cotización vigente al proveedor")
    if price.source_level.value == "D":
        ctx.review(severity=Severity.MEDIUM, category="cost_data", impact=Impact.MEDIUM, field_path=f"{path}.material",
                   description=f"{cid}: precio de material sólo paramétrico (nivel D)", action="Obtener cotización (nivel A)")

    gross = purchased * unit_price_p
    remnant = (purchased - consumed) * unit_price_p * credit / HUNDRED
    per_piece = gross - remnant
    src = CostSourceRef(kind="material_price", key=price.price_id, level=price.source_level.value, supplier=price.supplier,
                        reference=price.reference, price_date=price.price_date, age_days=age, recency=rec,
                        original_value=str(price.price_per_kg), original_currency=price.currency,
                        adjustment_factor=str(price.adjustment_factor), is_sample=price.is_sample)
    sources = [src] + ([s] if (s := ctx.fx_source(fx)) else [])
    inputs["price_per_kg"] = TraceInput(value=str(unit_price_p), unit=f"{ctx.currency}/kg", source=f"cost_master:{price.price_id} level {price.source_level.value} ({n_cands} candidatos)")
    inputs["component_multiplier"] = ctx.derived(mult, "pcs/unit", "Π quantity_per_parent")
    ctx.add(category="material", component_id=cid, description=f"{cid}: {grade} {form}",
            per_unit=per_piece * mult,
            quantities={"net_kg": str(net), "consumed_kg": str(consumed), "purchased_kg": str(purchased),
                        "net_formula": wformula},
            formula="net = " + wformula + "; consumed = net × (1+scrap%); purchased = consumed / util%; "
                    "cost = purchased × price − (purchased − consumed) × price × credit%; × multiplier",
            inputs=inputs, sources=sources,
            rule_refs=[ctx.rules.rule_ref("material")])

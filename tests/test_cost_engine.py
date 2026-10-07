import json
from decimal import Decimal

from conftest import AS_OF, comp, proc
from ts_quoter.cost_engine.engine import calculate
from ts_quoter.schemas.manufacturing import ManufacturingJob
from ts_quoter.schemas.results import LineStatus


def _calc(d, master, rules):
    return calculate(ManufacturingJob.model_validate(d), master, rules, AS_OF)


def line(res, cat, cid=None):
    return next(l for l in res.lines if l.category == cat and (cid is None or l.component_id == cid))


def test_material_net_consumed_purchased(demo_dict, master, rules):
    res = _calc(demo_dict, master, rules)
    l = line(res, "material", "C1")
    net = Decimal("700") * Decimal("500") * Decimal("1.5") * Decimal("1E-9") * Decimal("7930")
    consumed = net * Decimal("1.05")
    purchased = consumed / Decimal("0.75")
    assert Decimal(l.quantities["net_kg"]) == net
    assert Decimal(l.quantities["consumed_kg"]) == consumed
    assert Decimal(l.quantities["purchased_kg"]) == purchased
    assert l.per_unit == purchased * Decimal("92.50")
    # defaults de regla visibles como 'defaulted'
    assert "defaulted" in l.inputs["process_scrap_pct"].source


def test_price_hierarchy_prefers_level_a_not_cheapest(demo_dict, master, rules):
    res = _calc(demo_dict, master, rules)
    src = line(res, "material", "C1").sources[0]
    assert src.level == "A" and src.key == "S-MAT-001"  # D (78.00) es más barato pero no se usa


def test_grade_alias_normalized_raw_preserved(demo_dict, master, rules):
    res = _calc(demo_dict, master, rules)
    assert "AISI 304" in line(res, "material", "C1").description
    assert demo_dict["components"][1]["material"]["grade"]["value"] == "SS304"


def test_engine_does_not_mutate_input(demo_job, master, rules):
    before = demo_job.model_dump_json()
    calculate(demo_job, master, rules, AS_OF)
    assert demo_job.model_dump_json() == before


def test_deterministic(demo_job, master, rules):
    a = calculate(demo_job, master, rules, AS_OF).model_dump_json()
    b = calculate(demo_job, master, rules, AS_OF).model_dump_json()
    assert a == b


def test_unknown_weld_side_is_not_assumed(demo_dict, master, rules):
    j = proc(comp(demo_dict, "C1"), "P1-WELD")["joints"][0]
    j["side"] = {"value": None, "source_status": "unknown", "confidence": 0}
    res = _calc(demo_dict, master, rules)
    w = [l for l in res.lines if l.category == "welding" and l.component_id == "C1"]
    assert w[0].status == LineStatus.MISSING
    assert res.is_partial
    rv = [r for r in res.review_items if r.field_path and r.field_path.endswith("joints[0].side")]
    assert rv and rv[0].severity.value == "HIGH" and "ambos lados" in rv[0].question


def test_missing_material_grade_is_not_304(demo_dict, master, rules):
    comp(demo_dict, "C1")["material"]["grade"] = {"value": None, "source_status": "unknown", "confidence": 0}
    res = _calc(demo_dict, master, rules)
    l = line(res, "material", "C1")
    assert l.status == LineStatus.MISSING and "no se asume 304" in l.missing_reason


def test_missing_finish_is_not_no4(demo_dict, master, rules):
    proc(comp(demo_dict, "C1"), "P1-POL")["final_finish"] = {"value": None, "source_status": "unknown", "confidence": 0}
    res = _calc(demo_dict, master, rules)
    l = line(res, "surface_polishing", "C1")
    assert l.status == LineStatus.MISSING and "#4" in l.missing_reason


def test_missing_price_gives_partial_cost(demo_dict, master, rules):
    comp(demo_dict, "C3")["buy"]["unit_cost"] = {"value": None, "source_status": "unknown", "confidence": 0}
    res = _calc(demo_dict, master, rules)
    assert res.is_partial
    assert res.coverage.overall < 100
    assert any("Missing Cost" in (l.missing_reason or "") for l in res.lines)


def test_inch_input_equals_mm_input(demo_dict, master, rules):
    a = _calc(demo_dict, master, rules)
    c2 = comp(demo_dict, "C2")
    c2["material"]["outside_diameter"] = {"value": 0.5, "unit": "inch", "source_status": "explicit", "confidence": 1}
    b = _calc(demo_dict, master, rules)
    assert line(a, "material", "C2").per_unit == line(b, "material", "C2").per_unit


def test_component_quantity_per_assembly(demo_dict, master, rules):
    res = _calc(demo_dict, master, rules)
    buy = line(res, "buy_component", "C3")
    # 4 patas × USD 6.5 × FX protegido 19.00
    assert buy.per_unit == Decimal("4") * Decimal("6.5") * Decimal("19.00")
    assert any(s.kind == "fx" and Decimal(s.fx_rate) == Decimal("19") for s in buy.sources)


def test_setup_vs_run_scale_with_quantity(demo_job, master, rules):
    res = calculate(demo_job, master, rules, AS_OF)
    laser = line(res, "laser_cutting", "C1")
    assert laser.one_time > 0 and laser.per_unit > 0
    assert laser.total(Decimal(10)) == laser.one_time + laser.per_unit * 10


def test_every_complete_line_is_traceable(demo_job, master, rules):
    res = calculate(demo_job, master, rules, AS_OF)
    for l in res.lines:
        if l.status == LineStatus.COMPLETE:
            assert l.formula and l.inputs, l.line_id
            if l.category not in ("fixture",):
                assert l.sources, f"{l.line_id} sin fuente monetaria"

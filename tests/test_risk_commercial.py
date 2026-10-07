from decimal import Decimal

from conftest import AS_OF
from ts_quoter.commercial_engine.engine import recommend
from ts_quoter.cost_engine.engine import calculate
from ts_quoter.pipeline import run
from ts_quoter.risk_engine.engine import assess
from ts_quoter.schemas.manufacturing import ManufacturingJob


def test_risk_drivers_have_evidence(demo_job, master, rules):
    r = run(demo_job, master, rules, AS_OF).risk
    drivers = [d for c in (r.interpretation_risk, r.manufacturing_risk, r.cost_data_risk, r.commercial_risk, r.delivery_risk) for d in c.drivers]
    assert drivers
    for d in drivers:
        assert d.evidence and d.points == (d.weight * d.severity).quantize(Decimal("0.01"))


def test_margin_is_true_margin_not_markup(demo_job, master, rules):
    q = run(demo_job, master, rules, AS_OF).quote
    assert q.calculated_price == (q.total_internal_cost / (1 - Decimal("0.30"))).quantize(Decimal("0.01")) or \
        abs(q.calculated_price - q.total_internal_cost / Decimal("0.70")) < Decimal("0.02")
    assert q.calculated_price != (q.total_internal_cost * Decimal("1.30")).quantize(Decimal("0.01"))


def test_contingency_independent_of_margin(demo_dict, master, rules):
    demo_dict["commercial_inputs"]["target_margin_pct"] = 20
    a = run(ManufacturingJob.model_validate(demo_dict), master, rules, AS_OF)
    demo_dict["commercial_inputs"]["target_margin_pct"] = 40
    b = run(ManufacturingJob.model_validate(demo_dict), master, rules, AS_OF)
    assert a.quote.risk_contingency == b.quote.risk_contingency
    assert a.quote.calculated_price < b.quote.calculated_price


def test_global_contingency_within_band(demo_job, master, rules):
    g = rules.with_overrides({"risk.contingency_mode": "global"}, "test-global")
    cost = calculate(demo_job, master, g, AS_OF)
    r = assess(demo_job, cost, master, g)
    lo, hi = g.get(f"risk.contingency_bands_pct.{r.overall_risk}")
    assert all(lo <= l.pct <= hi for l in r.contingency_lines)


def test_unit_price_falls_with_quantity(demo_job, master, rules):
    q = run(demo_job, master, rules, AS_OF).quote
    prices = [b.suggested_unit_price for b in q.quantity_breaks]
    assert prices == sorted(prices, reverse=True)


def test_stop_condition_unknown_quantity(demo_dict, master, rules):
    demo_dict["project"]["quantity"] = {"value": None, "source_status": "unknown", "confidence": 0}
    q = run(ManufacturingJob.model_validate(demo_dict), master, rules, AS_OF).quote
    assert q.status == "BLOCKED" and "Cantidad desconocida" in q.stop_reasons


def test_proceed_with_assumptions(demo_dict, master, rules):
    demo_dict["project"]["quantity"] = {"value": None, "source_status": "unknown", "confidence": 0}
    demo_dict["commercial_inputs"]["proceed_with_assumptions"] = True
    demo_dict["commercial_inputs"]["proceed_approved_by"] = "gerente"
    q = run(ManufacturingJob.model_validate(demo_dict), master, rules, AS_OF).quote
    assert q.status == "PROCEED_WITH_ASSUMPTIONS"


def test_material_conflict_blocks(demo_dict, master, rules):
    demo_dict["conflicts"] = [{"conflict_id": "K1", "field_path": "components[1].material.grade",
                               "values": [{"value": "AISI 316L"}, {"value": "AISI 304"}],
                               "description": "Plano 316L; texto del cliente dice placas de refuerzo 304"}]
    res = run(ManufacturingJob.model_validate(demo_dict), master, rules, AS_OF)
    assert res.quote.status == "BLOCKED"
    assert res.cost.review_items[0].severity.value == "CRITICAL"


def test_never_autoquote_sent(demo_job, master, rules):
    q = run(demo_job, master, rules, AS_OF).quote
    assert "SENT" not in q.autoquote_class


def test_sample_data_flagged(demo_job, master, rules):
    res = run(demo_job, master, rules, AS_OF)
    assert res.cost.uses_sample_data
    assert any("SAMPLE DATA" in w for w in res.quote.warnings)

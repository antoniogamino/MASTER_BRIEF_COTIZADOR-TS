import json
from pathlib import Path

import httpx
import pytest

from conftest import AS_OF
from ts_quoter.config import Settings
from ts_quoter.interpreters.base import InterpreterInput
from ts_quoter.interpreters.payload import human_project_value
from ts_quoter.interpreters.text.interpreter import TextInterpreter
from ts_quoter.pipeline import run
from ts_quoter.providers.anthropic import AnthropicProvider
from ts_quoter.providers.base import AIProviderError, NullAIProvider, ReplayProvider
from ts_quoter.schemas.manufacturing import Project

FIX = Path(__file__).parent / "fixtures"
TEXT = (FIX / "rfq_charola.txt").read_text(encoding="utf-8")
RAW = (FIX / "ai_output_charola.json").read_text(encoding="utf-8")


def _project(qty=10):
    return Project(project_id="T1", quantity=human_project_value(qty), currency=human_project_value("MXN"))


def _interpret(raw=RAW, qty=10):
    it = TextInterpreter(ReplayProvider(raw))
    return it, it.interpret(InterpreterInput(project=_project(qty), text=TEXT))


def test_valid_citations_stay_explicit():
    _, r = _interpret()
    g = r.job.components[0].material.grade
    assert g.source_status.value == "explicit" and g.value == "AISI 304"
    assert r.job.interpretation_quality.interpreter == "text"
    assert r.job.interpretation_quality.prompt_version == "text/v1"


def test_fabricated_citation_on_critical_field_becomes_unknown():
    it, r = _interpret()
    side = r.job.components[0].processes[2].joints[0].side
    assert side.source_status.value == "unknown" and side.value is None
    assert any("sin cita verificable" in g for g in it.guard_log)


def test_quantity_discrepancy_creates_conflict_not_overwrite():
    _, r = _interpret(qty=10)
    assert r.job.project.quantity.value == 10
    assert any(c.field_path == "project.quantity" for c in r.job.conflicts)


def test_ai_cannot_invent_costs():
    data = json.loads(RAW)
    data["components"].append({"component_id": "C9", "description": "Rueda", "make_or_buy": "BUY",
                               "quantity_per_parent": {"value": 4, "source_status": "inferred", "confidence": 0.6},
                               "buy": {"unit_cost": {"value": 120, "source_status": "inferred", "confidence": 0.9}}})
    it, r = _interpret(json.dumps(data))
    c9 = next(c for c in r.job.components if c.component_id == "C9")
    assert c9.buy.unit_cost.value is None
    assert any("no inventa costos" in g for g in it.guard_log)


def test_ai_cannot_self_confirm():
    data = json.loads(RAW)
    data["components"][0]["material"]["form"]["source_status"] = "user_confirmed"
    _, r = _interpret(json.dumps(data))
    assert r.job.components[0].material.form.source_status.value == "inferred"


def test_hallucinated_field_fails_cleanly():
    data = json.loads(RAW)
    data["components"][0]["magic"] = 1
    _, r = _interpret(json.dumps(data))
    assert r.outcome == "failed_interpretation" and r.job is None and r.errors


def test_provider_down_does_not_crash():
    it = TextInterpreter(NullAIProvider())
    r = it.interpret(InterpreterInput(project=_project(), text=TEXT))
    assert r.outcome == "failed_interpretation" and "IA deshabilitada" in r.errors[0]


def test_interpreted_job_goes_through_cost_engine(master, rules):
    _, r = _interpret()
    res = run(r.job, master, rules, AS_OF)
    assert res.cost.is_partial  # lados de soldadura/pulido desconocidos -> no se asumen
    assert res.quote.status == "BLOCKED"  # conflicto de cantidad + costo crítico faltante
    assert res.quote.technical_questions


def test_anthropic_provider_structured_output(monkeypatch):
    monkeypatch.setenv("TSQ_AI_API_KEY", "test-key")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen["body"], seen["headers"] = body, req.headers
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "emit_result", "input": json.loads(RAW)}],
                                         "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}})

    cfg = Settings(ai_provider="anthropic", ai_text_model="model-from-env")
    prov = AnthropicProvider(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = TextInterpreter(prov).interpret(InterpreterInput(project=_project(), text=TEXT))
    assert r.job is not None and r.model == "model-from-env"
    assert seen["body"]["tool_choice"]["name"] == "emit_result"
    assert seen["headers"]["x-api-key"] == "test-key"
    assert "test-key" not in json.dumps(seen["body"])


def test_anthropic_missing_key(monkeypatch):
    monkeypatch.delenv("TSQ_AI_API_KEY", raising=False)
    prov = AnthropicProvider(Settings(ai_provider="anthropic", ai_text_model="m"))
    with pytest.raises(AIProviderError):
        prov.complete(TextInterpreter(prov).build_requests(InterpreterInput(project=_project(), text=TEXT))[0])

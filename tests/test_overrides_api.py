import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ts_quoter.schemas.overrides import apply_override


def test_override_keeps_original(demo_job):
    new = apply_override(demo_job, "components[1].processes[2].joints[0].penetration", "full", "ingeniero",
                         datetime(2026, 10, 6, tzinfo=timezone.utc), "confirmado con cliente")
    t = new.components[1].processes[2].joints[0].penetration
    assert t.value == "full" and t.source_status.value == "user_confirmed"
    ov = new.audit.overrides[-1]
    assert ov.original_value["source_status"] == "unknown" and ov.changed_by == "ingeniero"
    assert new.audit.interpretation_version == demo_job.audit.interpretation_version + 1
    assert demo_job.components[1].processes[2].joints[0].penetration.value is None  # original intacto


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TSQ_DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("TSQ_STORAGE_DIR", str(tmp_path / "storage"))
    import ts_quoter.config as cfg
    importlib.reload(cfg)
    import ts_quoter.db.repository as repo
    importlib.reload(repo)
    from ts_quoter.db.models import Base
    Base.metadata.create_all(repo.make_engine())
    import ts_quoter.api.main as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.app)


def test_api_vertical_slice(client, sample_xlsx, demo_dict):
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/projects", json={"project_code": "P-1", "customer": "Cliente Ejemplo", "user": "toño"})
    assert r.status_code == 200
    # calcular sin Cost Master -> error útil, no "something went wrong"
    client.post("/projects/P-1/interpretations", json=demo_dict)
    r = client.post("/projects/P-1/calculate", json={"as_of": "2026-10-06"})
    assert r.status_code == 409 and r.json()["detail"]["module"] == "cost_master"
    with open(sample_xlsx / "COST_MASTER_SAMPLE.xlsx", "rb") as fh:
        r = client.post("/cost-master/import", files={"file": ("COST_MASTER_SAMPLE.xlsx", fh)}, data={"user": "admin"})
    assert r.status_code == 200 and r.json()["is_sample"]
    r = client.post("/projects/P-1/calculate", json={"as_of": "2026-10-06", "user": "toño"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["quote"]["status"] == "RECOMMENDED"
    line = client.get("/projects/P-1/results/1/explain/L0008").json()
    assert line["formula"].startswith("hours =")
    r = client.post("/projects/P-1/overrides", json={"field_path": "components[1].processes[2].joints[0].penetration",
                                                     "new_value": "full", "user": "ingeniero", "reason": "plano DET A"})
    assert r.status_code == 200 and r.json()["version"] == 2
    second = client.post("/projects/P-1/calculate", json={"as_of": "2026-10-06"}).json()
    assert second["costing_version"] == 2
    assert float(second["quote"]["base_manufacturing_cost"]) > float(first["quote"]["base_manufacturing_cost"])
    assert client.get("/projects/P-1/results/1").json()["quote"]["base_manufacturing_cost"] == first["quote"]["base_manufacturing_cost"]
    actions = [a["action"] for a in client.get("/projects/P-1/audit").json()]
    for a in ("project_created", "interpretation_saved", "value_changed", "cost_recalculated", "risk_recalculated"):
        assert a in actions


def test_api_rejects_invalid_json(client, demo_dict):
    client.post("/projects", json={"project_code": "P-2"})
    demo_dict["components"][1]["material"]["grade"] = {"value": "AISI 304", "source_status": "unknown"}
    r = client.post("/projects/P-2/interpretations", json=demo_dict)
    assert r.status_code == 422 and r.json()["detail"]["module"] == "schemas"


def test_api_text_interpretation(client, monkeypatch):
    import ts_quoter.providers.anthropic as pa
    from ts_quoter.providers.base import ReplayProvider
    fx = Path(__file__).parent / "fixtures"
    monkeypatch.setattr(pa, "get_provider", lambda *a, **k: ReplayProvider((fx / "ai_output_charola.json").read_text(encoding="utf-8")))
    client.post("/projects", json={"project_code": "P-TXT"})
    r = client.post("/projects/P-TXT/interpret/text", json={"text": (fx / "rfq_charola.txt").read_text(encoding="utf-8"),
                                                             "quantity": 10, "currency": "MXN"})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "partial" and r.json()["guards"]
    monkeypatch.setattr(pa, "get_provider", lambda *a, **k: __import__("ts_quoter.providers.base", fromlist=["x"]).NullAIProvider())
    r = client.post("/projects/P-TXT/interpret/text", json={"text": "x"})
    assert r.status_code == 502 and r.json()["detail"]["data_lost"] is False
    assert any(a["action"] == "interpretation_executed" for a in client.get("/projects/P-TXT/audit").json())

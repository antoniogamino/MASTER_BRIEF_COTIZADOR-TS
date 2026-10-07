import json
from datetime import date
from pathlib import Path

import pytest

from ts_quoter.importers.excel import import_cost_master
from ts_quoter.rules.loader import load_rules
from ts_quoter.schemas.manufacturing import ManufacturingJob

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 10, 6)


@pytest.fixture(scope="session")
def rules():
    return load_rules(ROOT / "rules" / "default_rules_v1.yaml")


@pytest.fixture(scope="session")
def sample_xlsx(tmp_path_factory):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_sample_data
    out = tmp_path_factory.mktemp("sample")
    make_sample_data.main(out)
    return out


@pytest.fixture(scope="session")
def master(rules, sample_xlsx):
    m, rep = import_cost_master(sample_xlsx / "COST_MASTER_SAMPLE.xlsx", rules)
    assert m is not None, rep.summary()
    return m


@pytest.fixture
def demo_dict():
    return json.loads((ROOT / "sample_projects" / "charola_304_demo.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo_job(demo_dict):
    return ManufacturingJob.model_validate(demo_dict)


def comp(d, cid):
    return next(c for c in d["components"] if c["component_id"] == cid)


def proc(c, pid):
    return next(p for p in c["processes"] if p["process_id"] == pid)

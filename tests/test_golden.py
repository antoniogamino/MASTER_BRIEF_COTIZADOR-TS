import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_golden_cases_unchanged(sample_xlsx):
    sys.path.insert(0, str(ROOT / "scripts"))
    import regression
    for case in sorted((ROOT / "tests" / "golden").iterdir()):
        exp_p = case / "expected_cost_result.json"
        if not exp_p.exists():
            continue
        cur = regression.snapshot(case, sample_xlsx / "COST_MASTER_SAMPLE.xlsx")
        assert cur == json.loads(exp_p.read_text(encoding="utf-8")), f"golden {case.name} cambió: correr scripts/regression.py"

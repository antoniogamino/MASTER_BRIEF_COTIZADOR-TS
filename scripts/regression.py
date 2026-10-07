"""Regresión: compara la salida actual contra los golden cases y reporta cuánto cambió (sec. 106).

    python scripts/regression.py            # reporta diferencias
    python scripts/regression.py --update   # reescribe expected_cost_result.json (requiere revisión humana)
"""
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ts_quoter.importers.excel import import_cost_master  # noqa: E402
from ts_quoter.pipeline import run  # noqa: E402
from ts_quoter.rules.loader import load_rules  # noqa: E402
from ts_quoter.schemas.manufacturing import ManufacturingJob  # noqa: E402

AS_OF = date(2026, 10, 6)


def snapshot(case: Path, master_path: Path) -> dict:
    rules = load_rules()
    master, rep = import_cost_master(master_path, rules)
    assert master, rep.summary()
    job = ManufacturingJob.model_validate_json((case / "validated_interpretation.json").read_text(encoding="utf-8"))
    res = run(job, master, rules, AS_OF)
    by_cat: dict[str, Decimal] = {}
    q = Decimal(res.cost.quantity or 1)
    for l in res.cost.lines:
        if l.status.value == "complete":
            by_cat[l.category] = by_cat.get(l.category, Decimal(0)) + l.total(q)
    return {
        "as_of": str(AS_OF), "rule_set_ref": res.cost.rule_set_ref,
        "category_totals": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(by_cat.items())},
        "quote": {k: str(getattr(res.quote, k)) for k in ("status", "base_manufacturing_cost", "risk_contingency",
                                                         "total_internal_cost", "calculated_price", "rounded_price")},
        "risk": {"overall_score": str(res.risk.overall_score), "overall_risk": res.risk.overall_risk, "cei": str(res.risk.cei)},
        "missing_lines": [l.description for l in res.cost.lines if l.status.value == "missing"],
    }


def main(update: bool = False) -> int:
    import tempfile
    import make_sample_data
    tmp = Path(tempfile.mkdtemp())
    make_sample_data.main(tmp)
    worst = 0
    for case in sorted((ROOT / "tests" / "golden").iterdir()):
        if not (case / "validated_interpretation.json").exists():
            continue
        cur = snapshot(case, tmp / "COST_MASTER_SAMPLE.xlsx")
        exp_p = case / "expected_cost_result.json"
        if update or not exp_p.exists():
            exp_p.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"{case.name}: expected actualizado (REVISAR antes de commit)")
            continue
        exp = json.loads(exp_p.read_text(encoding="utf-8"))
        print(f"== {case.name}")
        for k in sorted(set(exp["category_totals"]) | set(cur["category_totals"])):
            a, b = Decimal(exp["category_totals"].get(k, "0")), Decimal(cur["category_totals"].get(k, "0"))
            if a != b:
                pct = ((b - a) / a * 100) if a else Decimal(100)
                worst = max(worst, abs(int(pct)))
                print(f"   {k:22} {a:>12} -> {b:>12}  ({pct:+.2f}%)")
        for k in exp["quote"]:
            if exp["quote"][k] != cur["quote"][k]:
                print(f"   quote.{k:16} {exp['quote'][k]} -> {cur['quote'][k]}")
        if exp == cur:
            print("   sin cambios")
    return worst


if __name__ == "__main__":
    sys.exit(1 if main("--update" in sys.argv) else 0)

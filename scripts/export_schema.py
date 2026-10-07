"""Exporta el JSON Schema formal y versionado del Manufacturing Cost JSON y del Cost Master."""
import json
from pathlib import Path

from ts_quoter import SCHEMA_VERSION
from ts_quoter.schemas.cost_master import CostMaster
from ts_quoter.schemas.manufacturing import ManufacturingJob
from ts_quoter.schemas.results import CostResult, QuoteRecommendation, RiskResult

out = Path(__file__).resolve().parents[1] / "docs" / "schema"
out.mkdir(parents=True, exist_ok=True)
for name, model in {"manufacturing_job": ManufacturingJob, "cost_master": CostMaster, "cost_result": CostResult,
                    "risk_result": RiskResult, "quote_recommendation": QuoteRecommendation}.items():
    sch = model.model_json_schema()
    sch["$id"] = f"ts-quoter/{name}/{SCHEMA_VERSION}"
    (out / f"{name}.schema.json").write_text(json.dumps(sch, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", out / f"{name}.schema.json")

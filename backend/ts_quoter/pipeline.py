"""Orquestación determinística: MCJ validado -> costo -> riesgo -> recomendación comercial.

Produce los artefactos de la sec. 192: validated.json, costing.json, risk.json, quote_summary.json, audit.json.
(interpreted.json lo produce el intérprete en fases 4-6.)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import ENGINE_VERSION, SCHEMA_VERSION
from .commercial_engine.engine import recommend
from .cost_engine.engine import calculate
from .risk_engine.engine import RISK_MODEL_VERSION, assess
from .rules.loader import RuleSet
from .schemas.cost_master import CostMaster
from .schemas.manufacturing import ManufacturingJob
from .schemas.results import CostResult, QuoteRecommendation, RiskResult
from .schemas.walk import iter_tracked


@dataclass
class PipelineResult:
    job: ManufacturingJob
    cost: CostResult
    risk: RiskResult
    quote: QuoteRecommendation

    def audit(self) -> dict[str, Any]:
        j = self.job
        return {
            "versions": {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
                         "risk_model_version": RISK_MODEL_VERSION, "rule_set_ref": self.cost.rule_set_ref,
                         "cost_master_version": self.cost.cost_master_version,
                         "interpretation_version": j.audit.interpretation_version,
                         "input_hash": self.cost.input_hash, "as_of_date": str(self.cost.as_of_date)},
            "sources": [d.model_dump(mode="json") for d in j.source_documents],
            "assumptions": [a.model_dump(mode="json") for a in j.assumptions],
            "overrides": [o.model_dump(mode="json") for o in j.audit.overrides],
            "conflicts": [c.model_dump(mode="json") for c in j.conflicts],
            "missing_costs": self.cost.coverage.missing_items,
            "risk_drivers": [d.model_dump(mode="json") for cat in (self.risk.interpretation_risk, self.risk.manufacturing_risk,
                                                                   self.risk.cost_data_risk, self.risk.commercial_risk,
                                                                   self.risk.delivery_risk) for d in cat.drivers],
            "field_status_counts": _status_counts(j),
            "uses_sample_data": self.cost.uses_sample_data,
        }

    def write(self, out_dir: str | Path) -> list[Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files = {
            "validated.json": self.job.model_dump(mode="json"),
            "costing.json": self.cost.model_dump(mode="json"),
            "risk.json": self.risk.model_dump(mode="json"),
            "quote_summary.json": self.quote.model_dump(mode="json"),
            "audit.json": self.audit(),
        }
        paths = []
        for name, data in files.items():
            p = out / name
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False), encoding="utf-8")
            paths.append(p)
        return paths


def _status_counts(job: ManufacturingJob) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, t in iter_tracked(job):
        out[t.source_status.value] = out.get(t.source_status.value, 0) + 1
    return out


def run(job: ManufacturingJob, master: CostMaster, rules: RuleSet, as_of: date) -> PipelineResult:
    cost = calculate(job, master, rules, as_of)
    risk = assess(job, cost, master, rules)
    quote = recommend(job, cost, risk, master, rules)
    logging.getLogger("tsq.calc").info(
        "project=%s input=%s rules=%s master=%s as_of=%s status=%s base=%s price=%s risk=%s cei=%s",
        job.project.project_id, cost.input_hash, cost.rule_set_ref, cost.cost_master_version, as_of,
        quote.status, quote.base_manufacturing_cost, quote.rounded_price, risk.overall_risk, risk.cei)
    return PipelineResult(job=job, cost=cost, risk=risk, quote=quote)

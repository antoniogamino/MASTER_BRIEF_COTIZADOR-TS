"""Resultados del Cost / Risk / Commercial Engine. Inmutables una vez guardados (se versionan)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field

from .common import ReviewItem, StrictModel


class LineStatus(str, Enum):
    COMPLETE = "complete"
    MISSING = "missing"  # no se pudo costear (falta dato técnico o precio) -> Partial Cost


class TraceInput(StrictModel):
    """Un insumo de una fórmula: valor + unidad + de dónde salió."""

    value: Optional[str] = None  # string para preservar Decimal exacto
    unit: Optional[str] = None
    source: str  # "mcj:components[0].material.thickness (explicit)", "rules@1.0.0#..:welding...", "cost_master:PO-4532"


class CostSourceRef(StrictModel):
    """Respuesta a '¿de dónde salió este número?' para montos."""

    kind: Literal["material_price", "process_rate", "labor_rate", "consumable", "packaging", "quality", "logistics", "supplier_quote", "manual", "fx"]
    key: str
    level: Optional[str] = None  # A-E
    supplier: Optional[str] = None
    reference: Optional[str] = None  # OC / cotización
    price_date: Optional[date] = None
    age_days: Optional[int] = None
    recency: Optional[str] = None  # fresh/acceptable/stale/obsolete
    original_value: Optional[str] = None
    original_currency: Optional[str] = None
    adjustment_factor: Optional[str] = None
    fx_rate: Optional[str] = None
    fx_source: Optional[str] = None
    fx_date: Optional[date] = None
    converted_value: Optional[str] = None
    is_sample: bool = False


class CostLine(StrictModel):
    line_id: str
    component_id: Optional[str] = None
    process_id: Optional[str] = None
    category: str  # material, laser_cutting, welding, welding_consumables, surface_polishing, ...
    description: str
    status: LineStatus
    # importes en moneda del proyecto
    one_time: Decimal = Decimal("0")  # setup / NRE: se amortiza en la cantidad
    per_unit: Decimal = Decimal("0")  # por unidad de producto cotizado
    hours_one_time: Decimal = Decimal("0")
    hours_per_unit: Decimal = Decimal("0")
    quantities: dict[str, str] = Field(default_factory=dict)  # net_kg, consumed_kg, purchased_kg, ...
    formula: str
    inputs: dict[str, TraceInput] = Field(default_factory=dict)
    sources: list[CostSourceRef] = Field(default_factory=list)
    rule_refs: list[str] = Field(default_factory=list)
    missing_reason: Optional[str] = None
    notes: list[str] = Field(default_factory=list)

    def total(self, qty: Decimal) -> Decimal:
        return self.one_time + self.per_unit * qty


class Coverage(StrictModel):
    by_category: dict[str, Decimal]  # % de líneas costeadas por categoría
    overall: Decimal
    missing_items: list[str]


class CostResult(StrictModel):
    """Salida del Cost Engine: costo base, sin riesgo ni margen."""

    costing_version: int = 1
    engine_version: str
    schema_version: str
    rule_set_ref: str
    cost_master_version: str
    input_hash: str
    as_of_date: date
    currency: str
    uses_sample_data: bool
    lines: list[CostLine]
    review_items: list[ReviewItem]
    coverage: Coverage
    is_partial: bool
    quantity: Optional[int]  # None si la cantidad es desconocida

    def base_total(self, qty: Decimal) -> Decimal:
        return sum((l.total(qty) for l in self.lines if l.status == LineStatus.COMPLETE), Decimal("0"))


# ----------------------------------------------------------------------------- risk
class RiskDriver(StrictModel):
    category: str
    factor: str
    weight: Decimal
    severity: Decimal  # 0-1
    points: Decimal
    evidence: str


class CategoryRisk(StrictModel):
    score: Decimal
    level: str
    drivers: list[RiskDriver]


class ContingencyLine(StrictModel):
    category: str
    base_amount: Decimal
    pct: Decimal
    amount: Decimal
    basis: str  # explicación


class CEIComponent(StrictModel):
    name: str
    score: Decimal
    weight: Decimal
    explanation: str


class RiskResult(StrictModel):
    risk_model_version: str
    rule_set_ref: str
    interpretation_risk: CategoryRisk
    manufacturing_risk: CategoryRisk
    cost_data_risk: CategoryRisk
    commercial_risk: CategoryRisk
    delivery_risk: CategoryRisk
    overall_score: Decimal
    overall_risk: str
    contingency_mode: str
    contingency_lines: list[ContingencyLine]
    rework_lines: list[ContingencyLine]
    contingency_total: Decimal
    rework_total: Decimal
    contingency_pct_effective: Decimal
    cei: Decimal
    cei_classification: str
    cei_components: list[CEIComponent]
    quantity_basis: Decimal


# ----------------------------------------------------------------------------- commercial
class PriceStep(StrictModel):
    label: str
    amount: Decimal
    formula: str


class QuantityBreak(StrictModel):
    quantity: int
    base_cost: Decimal
    contingency: Decimal
    total_internal_cost: Decimal
    suggested_price_total: Decimal
    suggested_unit_price: Decimal
    rounded_unit_price: Decimal


class QuoteRecommendation(StrictModel):
    status: Literal["RECOMMENDED", "BLOCKED", "PROCEED_WITH_ASSUMPTIONS", "PARTIAL_COST"]
    autoquote_class: str  # AUTOQUOTE_CANDIDATE ... (nunca AUTOQUOTE_SENT)
    currency: str
    quantity: Optional[int]
    steps: list[PriceStep]
    base_manufacturing_cost: Decimal
    risk_contingency: Decimal
    rework_contingency: Decimal
    adjusted_manufacturing_cost: Decimal
    manufacturing_overhead: Decimal
    administrative_overhead: Decimal
    commercial_costs: Decimal
    rush_premium: Decimal
    total_internal_cost: Decimal
    target_margin_pct: Decimal
    markup_pct_informative: Decimal
    calculated_price: Decimal
    rounded_price: Decimal
    approved_price: Optional[Decimal] = None
    unit_price_rounded: Optional[Decimal] = None
    quantity_breaks: list[QuantityBreak]
    stop_reasons: list[str]
    required_approvals: list[str]
    quote_notes: list[str]
    technical_questions: list[str]
    warnings: list[str]
    extra: dict[str, Any] = Field(default_factory=dict)

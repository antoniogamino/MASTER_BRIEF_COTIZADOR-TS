"""Cost Master: tarifas y precios importados de COST_MASTER.xlsx / HISTORICAL_PURCHASES.xlsx.

Cada registro conserva moneda original, fecha, proveedor y nivel de fuente (A–E).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import Field

from .common import StrictModel


class PriceLevel(str, Enum):
    """Jerarquía obligatoria de fuente de precio (sec. 22). A es la mejor."""

    A = "A"  # proveedor / cotización vigente
    B = "B"  # última compra real reciente
    C = "C"  # compra histórica actualizada (con adjustment_factor)
    D = "D"  # paramétrico interno
    E = "E"  # missing


LEVEL_RANK = {PriceLevel.A: 0, PriceLevel.B: 1, PriceLevel.C: 2, PriceLevel.D: 3, PriceLevel.E: 4}


class MaterialPrice(StrictModel):
    price_id: str
    grade: str  # normalizado: "AISI 304"
    grade_raw: Optional[str] = None
    form: str  # MaterialForm value
    thickness_min_mm: Optional[Decimal] = None
    thickness_max_mm: Optional[Decimal] = None
    price_per_kg: Decimal
    currency: str
    price_date: date
    supplier: Optional[str] = None
    source_level: PriceLevel
    source_type: str  # supplier_quote, purchase_order, historical, parametric
    reference: Optional[str] = None  # OC / cotización
    adjustment_factor: Decimal = Decimal("1")  # nivel C: histórico × factor
    possible_outlier: bool = False
    is_sample: bool = False


class ProcessRate(StrictModel):
    """Tarifa horaria por proceso / máquina (incluye mano de obra cargada si así se define)."""

    rate_key: str  # laser_cutting, bending, welding, surface_polishing, cnc_mill, passivation ...
    description: Optional[str] = None
    hourly_rate: Decimal
    currency: str
    rate_type: Literal["machine_plus_labor", "labor_only", "machine_only"] = "machine_plus_labor"
    labor_key: Optional[str] = None
    minimum_charge: Optional[Decimal] = None  # cargo mínimo por pedido para el proceso
    effective_date: Optional[date] = None
    estimated: bool = False  # tarifa estimada (riesgo cost_data: estimated_machine_rate)
    is_sample: bool = False


class LaborRate(StrictModel):
    labor_key: str
    salary_cost: Decimal
    benefits: Decimal = Decimal("0")
    burden: Decimal = Decimal("0")
    indirect: Decimal = Decimal("0")
    productive_hours_per_month: Decimal
    currency: str
    is_sample: bool = False

    @property
    def direct_hourly_rate(self) -> Decimal:
        return self.salary_cost / self.productive_hours_per_month

    @property
    def effective_hourly_rate(self) -> Decimal:
        """Tarifa totalmente cargada (fully burdened)."""
        return (self.salary_cost + self.benefits + self.burden + self.indirect) / self.productive_hours_per_month


class SimpleCostItem(StrictModel):
    """Consumibles, empaque, calidad y logística comparten esta forma."""

    item_key: str
    description: Optional[str] = None
    unit: str  # L, kg, ea, m3, m2, lot
    unit_cost: Decimal
    currency: str
    price_date: Optional[date] = None
    supplier: Optional[str] = None
    is_sample: bool = False


class FxRate(StrictModel):
    """Tipo de cambio: 1 ``base`` = rate ``quote``. Ej: base=USD, quote=MXN, current=18.40."""

    base: str
    quote: str
    reference_fx: Decimal
    current_fx: Decimal
    protected_fx: Decimal
    fx_date: date
    fx_source: str
    is_sample: bool = False


class RiskParameterOverride(StrictModel):
    factor_key: str
    weight: Decimal


class CostMaster(StrictModel):
    version: str  # checksum del archivo importado
    imported_at: datetime
    source_filename: Optional[str] = None
    is_sample: bool = False
    materials: list[MaterialPrice] = Field(default_factory=list)
    process_rates: list[ProcessRate] = Field(default_factory=list)
    labor: list[LaborRate] = Field(default_factory=list)
    consumables: list[SimpleCostItem] = Field(default_factory=list)
    packaging: list[SimpleCostItem] = Field(default_factory=list)
    quality: list[SimpleCostItem] = Field(default_factory=list)
    logistics: list[SimpleCostItem] = Field(default_factory=list)
    fx: list[FxRate] = Field(default_factory=list)
    risk_parameters: list[RiskParameterOverride] = Field(default_factory=list)

    def rate(self, key: str) -> Optional[ProcessRate]:
        return next((r for r in self.process_rates if r.rate_key == key), None)

    def item(self, table: str, key: str) -> Optional[SimpleCostItem]:
        return next((i for i in getattr(self, table) if i.item_key == key), None)

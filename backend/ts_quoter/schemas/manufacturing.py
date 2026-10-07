"""Manufacturing Cost JSON (MCJ) — esquema formal y versionado.

Todos los intérpretes (texto, dibujo, híbrido) y la captura manual producen este mismo objeto.
El Cost Engine sólo consume este objeto + Cost Master + Rule Set. Nunca llama a IA.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import Field, model_validator

from .. import SCHEMA_VERSION
from .common import RequirementStatus, ReviewItem, SourceRef, StrictModel, Tracked


# ----------------------------------------------------------------------------- enums
class ProjectStatus(str, Enum):
    DRAFT = "draft"
    INTERPRETING = "interpreting"
    REQUIRES_REVIEW = "requires_review"
    COSTING = "costing"
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    QUOTED = "quoted"
    WON = "won"
    LOST = "lost"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    FAILED_INTERPRETATION = "failed_interpretation"


class SourceType(str, Enum):
    DRAWING = "drawing"
    EMAIL = "email"
    RFQ = "rfq"
    SPECIFICATION = "specification"
    CUSTOMER_NOTE = "customer_note"
    INTERNAL_NOTE = "internal_note"
    PURCHASE_ORDER = "purchase_order"
    SUPPLIER_QUOTE = "supplier_quote"


class MakeOrBuy(str, Enum):
    MAKE = "MAKE"
    BUY = "BUY"
    UNKNOWN = "UNKNOWN"


class MaterialForm(str, Enum):
    SHEET = "sheet"
    PLATE = "plate"
    TUBE = "tube"
    SANITARY_TUBE = "sanitary_tube"
    PIPE = "pipe"
    ROUND_BAR = "round_bar"
    FLAT_BAR = "flat_bar"
    ANGLE = "angle"
    CHANNEL = "channel"
    SQUARE_TUBE = "square_tube"
    RECTANGULAR_TUBE = "rectangular_tube"
    WIRE = "wire"
    COMMERCIAL_COMPONENT = "commercial_component"
    OTHER = "other"


class Rush(str, Enum):
    NORMAL = "normal"
    URGENT = "urgent"
    EXPEDITE = "expedite"


class Side(str, Enum):
    ONE_SIDE = "one_side"
    BOTH_SIDES = "both_sides"
    UNKNOWN = "unknown"


class Accessibility(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    DIFFICULT = "difficult"
    VERY_DIFFICULT = "very_difficult"


# ----------------------------------------------------------------------------- project
class Project(StrictModel):
    project_id: str
    internal_reference: Optional[str] = None
    customer: Tracked[str] = Field(default_factory=Tracked[str])
    customer_part_number: Tracked[str] = Field(default_factory=Tracked[str])
    drawing_number: Tracked[str] = Field(default_factory=Tracked[str])
    drawing_revision: Tracked[str] = Field(default_factory=Tracked[str])
    description: Optional[str] = None
    product_family: Optional[str] = None  # charola, funnel, carro, soporte, ... (para reglas/similitud)
    quantity: Tracked[int] = Field(default_factory=Tracked[int])
    requested_delivery_date: Optional[date] = None
    destination_country: Tracked[str] = Field(default_factory=Tracked[str])
    destination_city: Tracked[str] = Field(default_factory=Tracked[str])
    currency: Tracked[str] = Field(default_factory=Tracked[str])  # moneda de cotización
    export: Tracked[bool] = Field(default_factory=Tracked[bool])
    quote_validity_days: int = 15
    rush: Rush = Rush.NORMAL
    first_time_build: Tracked[bool] = Field(default_factory=Tracked[bool])
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    status: ProjectStatus = ProjectStatus.DRAFT


class SourceDocument(StrictModel):
    document_id: str
    filename: str
    type: str  # mime / extensión
    checksum_sha256: str
    upload_date: datetime
    page_count: Optional[int] = None
    revision: Optional[str] = None
    source_type: SourceType
    sent_to_ai: bool = False  # transparencia: qué archivos se enviaron al proveedor de IA


# ----------------------------------------------------------------------------- geometry & material
class BoundingBox(StrictModel):
    length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    width: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    height: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))


class Geometry(StrictModel):
    """Geometría mínima para cálculo. ``blank_*`` = desarrollo plano (lámina/placa)."""

    bounding_box: BoundingBox = Field(default_factory=BoundingBox)
    blank_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    blank_width: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    cut_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))  # longitud de barra/tubo
    surface_area: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="m2"))


class Material(StrictModel):
    grade: Tracked[str] = Field(default_factory=Tracked[str])  # value normalizado (AISI 304); raw_value conserva "SS304"
    standard: Tracked[str] = Field(default_factory=Tracked[str])  # ASTM A240, A270...
    form: Tracked[MaterialForm] = Field(default_factory=Tracked[MaterialForm])
    finish: Tracked[str] = Field(default_factory=Tracked[str])  # acabado de compra (2B, #4...)
    thickness: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    gauge: Tracked[str] = Field(default_factory=Tracked[str])
    outside_diameter: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    inside_diameter: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    wall_thickness: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    schedule: Tracked[str] = Field(default_factory=Tracked[str])
    net_weight: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="kg"))  # override si se conoce
    commercial_size: Optional[str] = None
    purchase_unit: Optional[str] = "kg"
    # parámetros de aprovechamiento (si unknown -> se aplica default de regla, registrado como defaulted)
    process_scrap_pct: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="%"))
    sheet_utilization_pct: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="%"))
    remnant_credit_pct: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="%"))
    minimum_purchase_quantity_kg: Optional[float] = None


class Tolerance(StrictModel):
    feature: str
    value: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))  # ± valor real
    category: Optional[Literal["standard", "moderate", "tight", "very_tight"]] = None
    source_reference: Optional[SourceRef] = None


# ----------------------------------------------------------------------------- processes
class ProcessBase(StrictModel):
    process_id: str
    routing_sequence: int = 0
    description: Optional[str] = None
    # overrides manuales de tiempo (si se capturan, sustituyen el modelo paramétrico y quedan en traza)
    setup_time_override: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    run_time_override: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))  # por pieza
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_status: str = "explicit"
    source_reference: Optional[SourceRef] = None


class LaserCutting(ProcessBase):
    process_type: Literal["laser_cutting"] = "laser_cutting"
    cut_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    pierce_count: Tracked[int] = Field(default_factory=Tracked[int])
    parts_per_sheet: Optional[int] = None


class Bending(ProcessBase):
    process_type: Literal["bending"] = "bending"
    number_of_bends: Tracked[int] = Field(default_factory=Tracked[int])
    setup_count: int = 1
    tool_changes: int = 0
    handling_complexity: Literal["low", "medium", "high"] = "medium"


class Rolling(ProcessBase):
    process_type: Literal["rolling"] = "rolling"
    rolled_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))


class WeldJoint(StrictModel):
    joint_id: str
    process: Literal["GTAW", "GMAW", "other"] = "GTAW"
    joint_type: Literal["butt", "fillet", "lap", "corner", "other"] = "other"
    weld_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    weld_size: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    side: Tracked[Side] = Field(default_factory=Tracked[Side])  # NUNCA asumir both_sides por ver un lado
    continuity: Tracked[Literal["continuous", "intermittent"]] = Field(default_factory=Tracked[Literal["continuous", "intermittent"]])
    penetration: Tracked[Literal["partial", "full"]] = Field(default_factory=Tracked[Literal["partial", "full"]])
    purge_required: Tracked[bool] = Field(default_factory=Tracked[bool])
    sanitary: Tracked[bool] = Field(default_factory=Tracked[bool])
    accessibility: Tracked[Accessibility] = Field(default_factory=Tracked[Accessibility])
    position: Tracked[Literal["flat", "horizontal", "vertical", "overhead"]] = Field(default_factory=Tracked[Literal["flat", "horizontal", "vertical", "overhead"]])
    post_weld_grinding: Tracked[bool] = Field(default_factory=Tracked[bool])
    post_weld_polishing: Tracked[bool] = Field(default_factory=Tracked[bool])
    visual_requirement: Optional[str] = None
    surface_finish_requirement: Optional[str] = None
    source_reference: Optional[SourceRef] = None


class Welding(ProcessBase):
    process_type: Literal["welding"] = "welding"
    joints: list[WeldJoint] = Field(default_factory=list)


class SurfacePolishing(ProcessBase):
    """Pulido de superficie (A, D, E, F de la sec. 37). NO incluye acabado de soldadura."""

    process_type: Literal["surface_polishing"] = "surface_polishing"
    polish_kind: Literal["surface", "final_finishing", "sanitary", "cosmetic"] = "surface"
    area: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="m2"))
    sides: Tracked[Side] = Field(default_factory=Tracked[Side])
    initial_finish: Tracked[str] = Field(default_factory=Tracked[str])
    final_finish: Tracked[str] = Field(default_factory=Tracked[str])  # "#4", "Ra<=0.8"... visual != Ra
    geometry_type: Literal[
        "flat_surface", "bent_surface", "tube", "inside_corner", "outside_corner",
        "small_cavity", "large_open_surface", "complex_assembly",
    ] = "flat_surface"
    accessibility: Tracked[Accessibility] = Field(default_factory=Tracked[Accessibility])


class WeldFinishing(ProcessBase):
    """Acabado de soldadura (B, C de la sec. 37): esmerilado / difuminado / al ras."""

    process_type: Literal["weld_finishing"] = "weld_finishing"
    finishing_kind: Literal["weld_grinding", "weld_blending", "flush"] = "weld_blending"
    weld_length: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    weld_size: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="mm"))
    sides: Tracked[Side] = Field(default_factory=Tracked[Side])
    accessibility: Tracked[Accessibility] = Field(default_factory=Tracked[Accessibility])
    ra_requirement_um: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="um"))


class Machining(ProcessBase):
    process_type: Literal["machining"] = "machining"
    machine_type: Literal["cnc_lathe", "cnc_mill", "manual_lathe", "manual_mill", "drill_press"] = "cnc_mill"
    setup_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    cycle_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="min"))  # por pieza
    number_of_operations: int = 1
    stock_size: Optional[str] = None
    surface_finish: Optional[str] = None
    tooling_cost: Tracked[float] = Field(default_factory=Tracked[float])  # herramental especial (moneda del proyecto)
    special_fixture: bool = False


GenericProcessType = Literal[
    "plasma_cutting", "waterjet", "saw_cutting", "manual_cutting", "drilling", "turning", "milling",
    "cnc_machining", "threading", "tapping", "grinding", "passivation", "electropolishing",
    "assembly", "inspection", "cleaning", "packaging_labor", "unknown",
]


class GenericProcess(ProcessBase):
    """Proceso parametrizado por tiempo: setup (una vez) + run (por pieza) × tarifa del proceso."""

    process_type: GenericProcessType
    setup_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    run_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    handling_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    inspection_time: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))


class Outsourcing(ProcessBase):
    process_type: Literal["outsourcing"] = "outsourcing"
    outsourced_process: str
    supplier: Optional[str] = None
    supplier_quote_ref: Optional[str] = None
    cost_per_piece: Tracked[float] = Field(default_factory=Tracked[float])
    one_time_cost: Tracked[float] = Field(default_factory=Tracked[float])
    currency: Optional[str] = None
    quote_date: Optional[date] = None
    logistics_cost: Tracked[float] = Field(default_factory=Tracked[float])  # por lote


Process = Annotated[
    Union[LaserCutting, Bending, Rolling, Welding, SurfacePolishing, WeldFinishing, Machining, Outsourcing, GenericProcess],
    Field(discriminator="process_type"),
]


# ----------------------------------------------------------------------------- quality, buy, component
class QualityRequirement(StrictModel):
    item_key: str  # clave en Cost Master > Quality (p.ej. "cert_en10204_3_1", "dimensional_report")
    status: RequirementStatus = RequirementStatus.UNKNOWN
    basis: Literal["per_lot", "per_piece"] = "per_lot"
    quantity: float = 1
    source_reference: Optional[SourceRef] = None


class BuyInfo(StrictModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    part_number: Optional[str] = None
    supplier: Optional[str] = None
    unit_cost: Tracked[float] = Field(default_factory=Tracked[float])
    currency: Optional[str] = None
    moq: Optional[float] = None
    lead_time_days: Optional[int] = None
    price_date: Optional[date] = None
    price_source_ref: Optional[str] = None  # cotización / OC


class Component(StrictModel):
    component_id: str
    part_number: Optional[str] = None
    description: str
    parent_component_id: Optional[str] = None  # roll-up de ensambles / subensambles
    quantity_per_parent: Tracked[float] = Field(default_factory=Tracked[float])  # ≠ cantidad cotizada
    make_or_buy: MakeOrBuy = MakeOrBuy.UNKNOWN
    material: Optional[Material] = None
    geometry: Geometry = Field(default_factory=Geometry)
    processes: list[Process] = Field(default_factory=list)
    tolerances: list[Tolerance] = Field(default_factory=list)
    buy: Optional[BuyInfo] = None
    notes: Optional[str] = None
    source_reference: Optional[SourceRef] = None
    deleted: bool = False  # soft delete

    @model_validator(mode="after")
    def _unique_process_ids(self) -> "Component":
        ids = [p.process_id for p in self.processes]
        if len(ids) != len(set(ids)):
            raise ValueError(f"process_id duplicado en componente {self.component_id}")
        return self


# ----------------------------------------------------------------------------- packaging / logistics / engineering
class PackagingItem(StrictModel):
    item_key: str  # surface_protection, plastic_bag, desiccant, foam, nimf15, special_labeling...
    status: RequirementStatus = RequirementStatus.UNKNOWN
    basis: Literal["per_piece", "per_package", "per_lot"] = "per_package"
    quantity: float = 1


class PackagingRequirements(StrictModel):
    packaging_type: Tracked[Literal["none", "cardboard", "wood_crate", "pallet", "custom", "customer_specified"]] = Field(
        default_factory=Tracked
    )
    units_per_package: int = 1
    clearance_mm: Optional[float] = None  # si None -> default de regla
    items: list[PackagingItem] = Field(default_factory=list)


class LogisticsItem(StrictModel):
    item_key: str  # freight, insurance, customs_service, internal_transport, export_documentation
    status: RequirementStatus = RequirementStatus.UNKNOWN
    cost: Tracked[float] = Field(default_factory=Tracked[float])  # costo del lote
    currency: Optional[str] = None
    source_ref: Optional[str] = None


class Fixture(StrictModel):
    fixture_id: str
    fixture_type: str
    fixture_cost: Tracked[float] = Field(default_factory=Tracked[float])
    currency: Optional[str] = None
    reusable: bool = False
    amortization_quantity: Optional[int] = None


class Engineering(StrictModel):
    """No asumir cero: unknown genera alerta."""

    engineering_hours: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    cad_hours: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    programming_hours: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    manufacturing_planning_hours: Tracked[float] = Field(default_factory=lambda: Tracked[float](unit="hr"))
    fixtures: list[Fixture] = Field(default_factory=list)


# ----------------------------------------------------------------------------- epistemic objects
class Conflict(StrictModel):
    conflict_id: str
    field_path: str
    values: list[dict]  # [{"value":..., "source_reference": {...}}]
    description: str
    resolved: bool = False
    resolution: Optional[str] = None
    resolved_by: Optional[str] = None


class Uncertainty(StrictModel):
    uncertainty_id: str
    field_path: str
    description: str
    cost_impact: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class Assumption(StrictModel):
    assumption_id: str
    assumption: str
    reason: str
    field_path: Optional[str] = None
    cost_impact: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    risk_impact: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class InterpretationQuality(StrictModel):
    """Separa calidad del documento de confianza de la interpretación (sec. 167)."""

    drawing_quality_score: Optional[float] = Field(default=None, ge=0, le=100)
    interpretation_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    missing_pages: bool = False
    unreadable_notes: bool = False
    multiple_revisions: bool = False
    unclear_units: bool = False
    interpreter: Literal["manual", "text", "drawing", "hybrid"] = "manual"
    model: Optional[str] = None
    prompt_version: Optional[str] = None


class Override(StrictModel):
    field_path: str
    original_value: dict  # Tracked serializado completo
    new_value: dict
    changed_by: str
    changed_at: datetime
    reason: Optional[str] = None


class CommercialInputs(StrictModel):
    """Decisiones comerciales capturadas por humano (no por IA)."""

    target_margin_pct: Optional[float] = None  # None -> política de reglas
    proceed_with_assumptions: bool = False
    proceed_approved_by: Optional[str] = None
    quantity_breaks: list[int] = Field(default_factory=lambda: [1, 5, 10, 25])


class Audit(StrictModel):
    interpretation_version: int = 1
    overrides: list[Override] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- root
class ManufacturingJob(StrictModel):
    """Raíz del Manufacturing Cost JSON (sólo la parte de *interpretación*; los resultados viven aparte)."""

    schema_version: str = SCHEMA_VERSION
    project: Project
    source_documents: list[SourceDocument] = Field(default_factory=list)
    customer_requirements: list[str] = Field(default_factory=list)  # requisitos textuales (raw)
    components: list[Component] = Field(default_factory=list)
    quality_requirements: list[QualityRequirement] = Field(default_factory=list)
    packaging_requirements: PackagingRequirements = Field(default_factory=PackagingRequirements)
    logistics: list[LogisticsItem] = Field(default_factory=list)
    engineering: Engineering = Field(default_factory=Engineering)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    interpretation_quality: InterpretationQuality = Field(default_factory=InterpretationQuality)
    commercial_inputs: CommercialInputs = Field(default_factory=CommercialInputs)
    review_items: list[ReviewItem] = Field(default_factory=list)  # alertas generadas por el intérprete
    audit: Audit = Field(default_factory=Audit)

    @model_validator(mode="after")
    def _integrity(self) -> "ManufacturingJob":
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component_id duplicado")
        idset = set(ids)
        for c in self.components:
            if c.parent_component_id and c.parent_component_id not in idset:
                raise ValueError(f"{c.component_id}: parent_component_id '{c.parent_component_id}' no existe")
        # ciclos en árbol de ensamble
        parent = {c.component_id: c.parent_component_id for c in self.components}
        for cid in ids:
            seen, cur = set(), cid
            while cur:
                if cur in seen:
                    raise ValueError(f"ciclo en árbol de ensamble en {cid}")
                seen.add(cur)
                cur = parent.get(cur)
        return self

    def active_components(self) -> list[Component]:
        return [c for c in self.components if not c.deleted]

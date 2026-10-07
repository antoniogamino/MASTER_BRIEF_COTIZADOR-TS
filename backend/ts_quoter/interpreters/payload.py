"""Salida que se le pide a la IA (todo el MCJ excepto lo que define el humano) y su fusión con el proyecto.

El humano define: cliente, cantidad, moneda, destino, exportación, margen. Si el texto del cliente dice
otra cosa (p.ej. otra cantidad) NO se reemplaza: se crea un objeto Conflict (sec. 9).
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..schemas.common import ReviewItem, SourceStatus, StrictModel, Tracked
from ..schemas.manufacturing import (Assumption, Component, Conflict, Engineering, LogisticsItem, ManufacturingJob,
                                     PackagingRequirements, Project, QualityRequirement, Uncertainty)


class ProjectHints(StrictModel):
    """Lo que el documento dice sobre el proyecto (para comparar contra lo capturado por el usuario)."""

    description: Optional[str] = None
    product_family: Optional[str] = None
    customer: Tracked[str] = Field(default_factory=Tracked[str])
    customer_part_number: Tracked[str] = Field(default_factory=Tracked[str])
    drawing_number: Tracked[str] = Field(default_factory=Tracked[str])
    drawing_revision: Tracked[str] = Field(default_factory=Tracked[str])
    quantity: Tracked[int] = Field(default_factory=Tracked[int])
    currency: Tracked[str] = Field(default_factory=Tracked[str])
    export: Tracked[bool] = Field(default_factory=Tracked[bool])
    destination_country: Tracked[str] = Field(default_factory=Tracked[str])
    destination_city: Tracked[str] = Field(default_factory=Tracked[str])
    first_time_build: Tracked[bool] = Field(default_factory=Tracked[bool])


class InterpretationPayload(StrictModel):
    project_hints: ProjectHints = Field(default_factory=ProjectHints)
    customer_requirements: list[str] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    quality_requirements: list[QualityRequirement] = Field(default_factory=list)
    packaging_requirements: PackagingRequirements = Field(default_factory=PackagingRequirements)
    logistics: list[LogisticsItem] = Field(default_factory=list)
    engineering: Engineering = Field(default_factory=Engineering)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    interpretation_confidence: float = Field(default=0.5, ge=0, le=1)


MERGE_FIELDS = ["customer", "customer_part_number", "drawing_number", "drawing_revision", "quantity", "currency",
                "export", "destination_country", "destination_city", "first_time_build"]


def merge(project: Project, payload: InterpretationPayload) -> ManufacturingJob:
    """Proyecto (humano) + interpretación (IA). Lo humano manda; discrepancias -> Conflict visible."""
    proj = project.model_copy(deep=True)
    conflicts = list(payload.conflicts)
    h = payload.project_hints
    if not proj.description and h.description:
        proj.description = h.description
    if not proj.product_family and h.product_family:
        proj.product_family = h.product_family
    for f in MERGE_FIELDS:
        mine: Tracked = getattr(proj, f)
        theirs: Tracked = getattr(h, f)
        if not theirs.known:
            continue
        if not mine.known:
            setattr(proj, f, theirs)  # el documento lo dice y el usuario no lo capturó
        elif str(mine.value).strip().lower() != str(theirs.value).strip().lower():
            conflicts.append(Conflict(
                conflict_id=f"K-PRJ-{f}", field_path=f"project.{f}",
                values=[{"value": mine.value, "source": f"capturado ({mine.source_status.value})"},
                        {"value": theirs.value, "source": "documento",
                         "source_reference": theirs.source_reference.model_dump() if theirs.source_reference else None}],
                description=f"{f}: capturado '{mine.value}' vs documento '{theirs.value}'"))
    return ManufacturingJob(
        project=proj, customer_requirements=payload.customer_requirements, components=payload.components,
        quality_requirements=payload.quality_requirements, packaging_requirements=payload.packaging_requirements,
        logistics=payload.logistics, engineering=payload.engineering, uncertainties=payload.uncertainties,
        conflicts=conflicts, assumptions=payload.assumptions, review_items=payload.review_items)


def human_project_value(value, unit: Optional[str] = None) -> dict:
    """Dato capturado por el usuario en el formulario del proyecto."""
    return {"value": value, "unit": unit, "source_status": SourceStatus.USER_CONFIRMED.value, "confidence": 1.0}

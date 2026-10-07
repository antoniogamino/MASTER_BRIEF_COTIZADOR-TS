"""ManufacturingInterpreter: abstracción común de los tres intérpretes (texto, dibujo, híbrido).

Todos producen el MISMO Manufacturing Cost JSON. Flujo:
    RAW INPUT -> FACT EXTRACTION -> TECHNICAL INTERPRETATION -> MANUFACTURING INFERENCE -> JSON
    -> validación Pydantic -> (reparación controlada, 1 intento) -> valid | partial | failed_interpretation

Implementación: fase 4 (texto), 5 (dibujo), 6 (híbrido). Aquí queda el contrato y el manejo de fallas.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import ValidationError

from ..providers.base import AIProvider, AIProviderError, AIRequest
from ..schemas.manufacturing import ManufacturingJob, Project

Outcome = Literal["valid", "partial", "failed_interpretation"]


@dataclass
class InterpreterInput:
    project: Project
    text: Optional[str] = None
    document_paths: list[str] = field(default_factory=list)


@dataclass
class InterpretationRun:
    outcome: Outcome
    job: Optional[ManufacturingJob]
    raw_output: Optional[str]
    errors: list[str]
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    files_sent_to_ai: list[str] = field(default_factory=list)


class ManufacturingInterpreter(ABC):
    kind: Literal["text", "drawing", "hybrid"]
    prompt_version: str

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    @abstractmethod
    def build_requests(self, inp: InterpreterInput) -> list[AIRequest]:
        """Construye las solicitudes (extracción de hechos, interpretación). Prompts versionados en /prompts."""

    def interpret(self, inp: InterpreterInput) -> InterpretationRun:
        """Ejecuta, valida y nunca pierde el proyecto ante fallas (sec. 83-85)."""
        reqs = self.build_requests(inp)
        sent = sorted({f for r in reqs for f in r.files})
        try:
            resp = None
            for r in reqs:
                resp = self.provider.complete(r)
        except AIProviderError as e:
            return InterpretationRun("failed_interpretation", None, None, [f"proveedor IA: {e}"], files_sent_to_ai=sent)
        assert resp is not None
        job, errors = self.to_job(resp.raw_text, inp)
        if job is None:
            repaired = self._repair(resp.raw_text, errors)
            if repaired is not None:
                job, errors2 = self.to_job(repaired, inp)
                errors = errors + errors2 if job is None else []
        if job is not None:
            job.interpretation_quality.model = resp.model
        outcome: Outcome = "failed_interpretation" if job is None else ("partial" if job.uncertainties or errors else "valid")
        return InterpretationRun(outcome, job, resp.raw_text, errors, resp.model, self.prompt_version,
                                 resp.input_hash, resp.output_hash, sent)

    def output_schema(self) -> dict:
        """Esquema que debe cumplir la salida de la IA (por defecto, el MCJ completo)."""
        return ManufacturingJob.model_json_schema()

    def to_job(self, raw: str, inp: InterpreterInput) -> tuple[Optional[ManufacturingJob], list[str]]:
        """Convierte la salida cruda en MCJ validado (los intérpretes pueden fusionar datos del proyecto)."""
        return self._validate(raw)

    @staticmethod
    def _validate(raw: str) -> tuple[Optional[ManufacturingJob], list[str]]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, [f"JSON inválido: {e}"]
        try:
            return ManufacturingJob.model_validate(data), []
        except ValidationError as e:
            return None, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:30]]

    def _repair(self, raw: str, errors: list[str]) -> Optional[str]:
        """Reparación controlada: un solo intento, pidiendo corregir SÓLO errores de esquema (sin agregar datos)."""
        try:
            resp = self.provider.complete(AIRequest(purpose="repair_json", prompt_version=f"{self.prompt_version}-repair",
                                                    system="Corrige únicamente la estructura JSON para cumplir el esquema. "
                                                           "No agregues ni inventes valores; usa source_status=unknown si falta un dato.",
                                                    text=json.dumps({"errors": errors, "json": raw})[:200_000],
                                                    json_schema=self.output_schema()))
            return resp.raw_text
        except AIProviderError:
            return None


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]

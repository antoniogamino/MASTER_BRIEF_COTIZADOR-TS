"""Interfaces de proveedores externos. Ninguna lógica de costo depende de ellas.

Implementaciones previstas: Anthropic, OpenAI, modelo local (AIProvider); Banxico/DOF u otros (ExchangeRateProvider);
INEGI/INPC (InflationProvider); índices de acero (MaterialIndexProvider). Odoo (OdooGateway) — sólo lectura en MVP+1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional


@dataclass
class AIRequest:
    purpose: str  # "fact_extraction" | "technical_interpretation" | "repair_json"
    prompt_version: str
    system: str
    text: Optional[str] = None
    files: list[str] = field(default_factory=list)  # rutas de archivos a enviar (se registran como sent_to_ai)
    json_schema: Optional[dict] = None
    model_role: str = "text"  # text | vision | fallback  (el nombre de modelo vive sólo en config)


@dataclass
class AIResponse:
    model: str
    raw_text: str
    input_hash: str
    output_hash: str
    usage: dict[str, Any] = field(default_factory=dict)


class AIProviderError(RuntimeError):
    """API caída, timeout, respuesta parcial... El proyecto nunca se pierde: el estado se guarda antes de llamar."""


class AIProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def complete(self, req: AIRequest) -> AIResponse: ...


class NullAIProvider(AIProvider):
    """Modo offline / sin IA: cualquier llamada falla con mensaje claro; costeo sigue funcionando."""

    name = "none"

    def complete(self, req: AIRequest) -> AIResponse:
        raise AIProviderError("IA deshabilitada (TSQ_AI_PROVIDER=none o sin conexión). Captura manual y costeo siguen disponibles.")


class ExchangeRateProvider(ABC):
    @abstractmethod
    def rate(self, base: str, quote: str, on: date) -> tuple[Decimal, str]: ...


class InflationProvider(ABC):
    @abstractmethod
    def factor(self, from_date: date, to_date: date) -> tuple[Decimal, str]: ...


class MaterialIndexProvider(ABC):
    @abstractmethod
    def index(self, grade: str, form: str, on: date) -> tuple[Decimal, str]: ...


class OdooGateway(ABC):
    """Futuro (sec. 128). Escritura limitada a borrador de cotización y sólo con aprobación humana."""

    @abstractmethod
    def read_purchase_orders(self, since: date) -> list[dict]: ...

    @abstractmethod
    def read_vendors(self) -> list[dict]: ...


class ReplayProvider(AIProvider):
    """Devuelve una salida previamente generada (archivo JSON). Sirve para pruebas, regresión y para
    procesar una interpretación hecha fuera del sistema: igual pasa por validación y guardas."""

    name = "replay"

    def __init__(self, raw_json: str, model: str = "replay") -> None:
        self.raw = raw_json
        self.model = model

    def complete(self, req: AIRequest) -> AIResponse:
        import hashlib
        h = lambda s: hashlib.sha256(s.encode()).hexdigest()[:16]  # noqa: E731
        return AIResponse(model=self.model, raw_text=self.raw, input_hash=h((req.text or "") + req.system), output_hash=h(self.raw))

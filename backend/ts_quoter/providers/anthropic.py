"""Proveedor Anthropic (Messages API) vía httpx. Salida estructurada forzada con tool use.

El nombre del modelo NO está en el código: viene de TSQ_AI_TEXT_MODEL / TSQ_AI_VISION_MODEL / TSQ_AI_FALLBACK_MODEL.
La API key se lee en el momento de la llamada y nunca se registra.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import time
from pathlib import Path

import httpx

from ..config import Settings, settings
from .base import AIProvider, AIProviderError, AIRequest, AIResponse

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
log = logging.getLogger("tsq.ai")


def _h(s: str | bytes) -> str:
    return hashlib.sha256(s if isinstance(s, bytes) else s.encode()).hexdigest()[:16]


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, cfg: Settings = settings, client: httpx.Client | None = None, max_tokens: int = 16000) -> None:
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=cfg.ai_timeout_s)
        self.max_tokens = max_tokens

    def _model(self, role: str) -> str:
        m = {"text": self.cfg.ai_text_model, "vision": self.cfg.ai_vision_model or self.cfg.ai_text_model,
             "fallback": self.cfg.ai_fallback_model}.get(role) or ""
        if not m:
            raise AIProviderError(f"Modelo IA para rol '{role}' no configurado (TSQ_AI_{role.upper()}_MODEL en .env)")
        return m

    def _content(self, req: AIRequest) -> list[dict]:
        blocks: list[dict] = []
        for f in req.files:  # fase 5: PDFs / imágenes
            p = Path(f)
            mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            data = base64.b64encode(p.read_bytes()).decode()
            kind = "document" if mt == "application/pdf" else "image"
            blocks.append({"type": kind, "source": {"type": "base64", "media_type": mt, "data": data}})
        if req.text:
            blocks.append({"type": "text", "text": req.text})
        return blocks

    def complete(self, req: AIRequest) -> AIResponse:
        key = Settings.ai_api_key()
        if not key:
            raise AIProviderError("TSQ_AI_API_KEY no configurada en .env")
        roles = [req.model_role] + (["fallback"] if req.model_role != "fallback" and self.cfg.ai_fallback_model else [])
        last_err = ""
        for role in roles:
            model = self._model(role)
            body: dict = {"model": model, "max_tokens": self.max_tokens, "system": req.system,
                          "messages": [{"role": "user", "content": self._content(req)}]}
            if req.json_schema:
                body["tools"] = [{"name": "emit_result", "description": "Devuelve el resultado estructurado.",
                                  "input_schema": req.json_schema}]
                body["tool_choice"] = {"type": "tool", "name": "emit_result"}
            payload = json.dumps(body, ensure_ascii=False)
            in_hash = _h(payload)
            for attempt in range(3):
                t0 = time.monotonic()
                try:
                    r = self.client.post(API_URL, content=payload.encode(),
                                         headers={"x-api-key": key, "anthropic-version": API_VERSION,
                                                  "content-type": "application/json"})
                except httpx.HTTPError as e:  # timeout / red
                    last_err = f"{type(e).__name__}: {e}"
                    log.warning("ai_error model=%s purpose=%s attempt=%d err=%s", model, req.purpose, attempt, last_err)
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code in (429, 500, 502, 503, 529):
                    last_err = f"HTTP {r.status_code}"
                    log.warning("ai_retry model=%s status=%s attempt=%d", model, r.status_code, attempt)
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code >= 400:
                    raise AIProviderError(f"Anthropic HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
                raw = _extract(data, bool(req.json_schema))
                if data.get("stop_reason") == "max_tokens":
                    log.warning("ai_truncated model=%s purpose=%s", model, req.purpose)
                out_hash = _h(raw)
                log.info("ai_call model=%s purpose=%s prompt=%s in=%s out=%s ms=%d usage=%s stop=%s files=%s",
                         model, req.purpose, req.prompt_version, in_hash, out_hash, (time.monotonic() - t0) * 1000,
                         data.get("usage"), data.get("stop_reason"), [Path(f).name for f in req.files])
                return AIResponse(model=model, raw_text=raw, input_hash=in_hash, output_hash=out_hash,
                                  usage=data.get("usage") or {})
        raise AIProviderError(f"IA no disponible tras reintentos: {last_err}")


def _extract(data: dict, structured: bool) -> str:
    content = data.get("content") or []
    if structured:
        for b in content:
            if b.get("type") == "tool_use":
                return json.dumps(b.get("input"), ensure_ascii=False)
        raise AIProviderError("Respuesta sin bloque estructurado (tool_use)")
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def get_provider(cfg: Settings = settings) -> AIProvider:
    from .base import NullAIProvider

    if cfg.ai_provider == "anthropic":
        return AnthropicProvider(cfg)
    return NullAIProvider()

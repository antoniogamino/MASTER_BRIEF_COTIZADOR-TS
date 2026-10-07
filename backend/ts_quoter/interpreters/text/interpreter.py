"""Interpreter 1 — TEXT (fase 4).

RAW TEXT -> IA (prompt versionado, salida estructurada) -> InterpretationPayload -> merge con proyecto
-> guardas determinísticas -> MCJ validado (interpreted.json)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ...config import ROOT
from ...providers.base import AIRequest
from ...schemas.manufacturing import ManufacturingJob
from ..base import InterpreterInput, ManufacturingInterpreter
from ..guards import apply_guards
from ..payload import MERGE_FIELDS, InterpretationPayload, merge

PROMPT_DIR = ROOT / "prompts" / "text"


def load_prompt(version: str) -> str:
    p = PROMPT_DIR / f"{version}.md"
    if not p.exists():
        raise FileNotFoundError(f"prompt no encontrado: {p}")
    return p.read_text(encoding="utf-8")


class TextInterpreter(ManufacturingInterpreter):
    kind = "text"

    def __init__(self, provider, prompt_version: str = "v1") -> None:
        super().__init__(provider)
        self.prompt_version = f"text/{prompt_version}"
        self._system = load_prompt(prompt_version)
        self.guard_log: list[str] = []

    def output_schema(self) -> dict:
        return InterpretationPayload.model_json_schema()

    def build_requests(self, inp: InterpreterInput) -> list[AIRequest]:
        if not inp.text or not inp.text.strip():
            raise ValueError("TextInterpreter requiere texto")
        ctx = {k: getattr(inp.project, k).value for k in MERGE_FIELDS if getattr(inp.project, k).known}
        user = ("Datos ya capturados por el usuario (no los repitas como hechos del texto; si el texto los contradice, "
                f"repórtalo en project_hints con cita): {json.dumps(ctx, ensure_ascii=False, default=str)}\n\n"
                f"=== TEXTO DEL CLIENTE ===\n{inp.text}\n=== FIN ===")
        return [AIRequest(purpose="technical_interpretation", prompt_version=self.prompt_version, system=self._system,
                          text=user, json_schema=self.output_schema(), model_role="text")]

    def to_job(self, raw: str, inp: InterpreterInput) -> tuple[Optional[ManufacturingJob], list[str]]:
        try:
            payload = InterpretationPayload.model_validate(json.loads(raw))
        except json.JSONDecodeError as e:
            return None, [f"JSON inválido: {e}"]
        except ValidationError as e:
            return None, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:30]]
        try:
            job = merge(inp.project, payload)
        except ValidationError as e:
            return None, [f"merge: {x['loc']}: {x['msg']}" for x in e.errors()[:30]]
        user_paths = {f"project.{f}" for f in MERGE_FIELDS if getattr(inp.project, f).known}
        job, self.guard_log = apply_guards(job, inp.text or "", user_paths)
        iq = job.interpretation_quality
        iq.interpreter = "text"
        iq.prompt_version = self.prompt_version
        iq.interpretation_confidence = payload.interpretation_confidence
        return job, []

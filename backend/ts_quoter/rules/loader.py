"""Carga del Rule Set versionado. El hash del contenido viaja con cada resultado (reproducibilidad)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import yaml

from ..config import settings


class RuleError(KeyError):
    """Regla faltante: error explícito con ruta (nunca default silencioso)."""


class RuleSet:
    """Envoltorio de solo lectura sobre el YAML de reglas.

    ``get("welding.productivity_m_per_hr.GTAW")`` -> Decimal | str | dict.
    Cada acceso queda registrado en ``used`` para la traza de auditoría.
    """

    def __init__(self, data: dict[str, Any], source: str = "<memory>") -> None:
        self._data = data
        self.source = source
        self.version: str = str(data["rule_set_version"])
        self.is_sample: bool = bool(data.get("is_sample", False))
        canonical = json.dumps(data, sort_keys=True, default=str).encode()
        self.hash: str = hashlib.sha256(canonical).hexdigest()[:16]

    @property
    def ref(self) -> str:
        return f"rules@{self.version}#{self.hash}"

    def raw(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._data, default=str))

    def get(self, path: str, default: Any = ...) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is not ...:
                    return default
                raise RuleError(f"Regla no encontrada: '{path}' en {self.ref}")
        return _to_decimal(node)

    def lookup(self, path: str, key: str, default: Any = ...) -> Any:
        """Busca ``key`` dentro del dict en ``path`` (las claves pueden contener puntos, p.ej. 'Ra<=0.8')."""
        table = self.get(path)
        if key in table:
            return table[key]
        if default is not ...:
            return default
        raise RuleError(f"Regla no encontrada: '{path}[{key}]' en {self.ref}")

    def rule_ref(self, path: str) -> str:
        return f"{self.ref}:{path}"

    def band(self, path: str, value: Decimal, key: str, out: str = "factor") -> tuple[Decimal, str]:
        """Busca en una tabla de bandas ordenada por límite superior inclusivo."""
        rows = self.get(path)
        for i, row in enumerate(rows):
            if value <= row[key]:
                return row[out], f"{path}[{i}]"
        return rows[-1][out], f"{path}[{len(rows) - 1}]"

    def with_overrides(self, overrides: dict[str, Any], label: str) -> "RuleSet":
        """Nueva versión derivada (nunca muta la original)."""
        data = json.loads(json.dumps(self._data, default=str))
        for path, value in overrides.items():
            node = data
            parts = path.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value
        data["rule_set_version"] = f"{self.version}+{label}"
        return RuleSet(data, source=f"{self.source}+{label}")


def _to_decimal(node: Any) -> Any:
    if isinstance(node, bool):
        return node
    if isinstance(node, (int, float)):
        return Decimal(str(node))
    if isinstance(node, dict):
        return {k: _to_decimal(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_to_decimal(v) for v in node]
    return node


def load_rules(path: Optional[str | Path] = None) -> RuleSet:
    p = Path(path or settings.rules_path)
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if "rule_set_version" not in data:
        raise RuleError(f"{p}: falta rule_set_version")
    return RuleSet(data, source=str(p))

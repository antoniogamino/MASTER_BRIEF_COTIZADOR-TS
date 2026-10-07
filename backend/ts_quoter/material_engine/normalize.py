"""Normalización de materiales: raw_value se conserva, normalized_value se calcula por alias."""

from __future__ import annotations

import re
from typing import Optional

from ..rules.loader import RuleSet


def _key(s: str) -> str:
    return re.sub(r"[\s\-_.]", "", s).upper()


def normalize_grade(raw: str, rules: RuleSet) -> Optional[str]:
    """'SS304' -> 'AISI 304'. Devuelve None si no hay alias (no se adivina)."""
    aliases: dict[str, list[str]] = rules.get("material.grade_aliases")
    k = _key(raw)
    for canonical, alist in aliases.items():
        if k == _key(canonical) or any(k == _key(a) for a in alist):
            return canonical
    return None

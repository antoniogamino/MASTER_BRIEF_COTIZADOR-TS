"""Override humano auditable: el valor original nunca se borra (queda en audit.overrides)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from .common import SourceRef, SourceStatus, Tracked
from .manufacturing import ManufacturingJob, Override

_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?")


class OverrideError(ValueError):
    pass


def _resolve(root: BaseModel, path: str) -> tuple[Any, str]:
    parts = path.split(".")
    node: Any = root
    for part in parts[:-1]:
        m = _TOKEN.fullmatch(part)
        if not m:
            raise OverrideError(f"segmento inválido '{part}'")
        node = getattr(node, m.group(1))
        if m.group(2) is not None:
            node = node[int(m.group(2))]
    return node, parts[-1]


def apply_override(job: ManufacturingJob, path: str, new_value: Any, changed_by: str, changed_at: datetime,
                   reason: Optional[str] = None, unit: Optional[str] = None) -> ManufacturingJob:
    """Devuelve un NUEVO job con el campo Tracked en ``path`` marcado user_confirmed.

    El interpretation_version se incrementa (nunca se sobreescribe el análisis anterior).
    """
    new = job.model_copy(deep=True)
    parent, attr = _resolve(new, path)
    current = getattr(parent, attr, None)
    if not isinstance(current, Tracked):
        raise OverrideError(f"'{path}' no es un campo rastreable (Tracked)")
    original = current.model_dump(mode="json")
    tracked_cls = type(current)
    replacement = tracked_cls(
        value=new_value,
        unit=unit or current.unit,
        source_status=SourceStatus.USER_CONFIRMED if new_value is not None else SourceStatus.UNKNOWN,
        confidence=1.0 if new_value is not None else 0.0,
        source_reference=SourceRef(note=f"override por {changed_by}: {reason or 'sin motivo'}"),
        raw_value=current.raw_value,
    )
    setattr(parent, attr, replacement)
    new.audit.overrides.append(Override(field_path=path, original_value=original, new_value=replacement.model_dump(mode="json"),
                                        changed_by=changed_by, changed_at=changed_at, reason=reason))
    new.audit.interpretation_version += 1
    return ManufacturingJob.model_validate(new.model_dump())  # revalida esquema completo

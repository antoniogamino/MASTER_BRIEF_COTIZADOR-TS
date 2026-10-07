"""Recorre el MCJ y devuelve todos los campos Tracked con su ruta (para CEI, riesgo y auditoría)."""

from __future__ import annotations

from typing import Iterator

from pydantic import BaseModel

from .common import Tracked


def iter_tracked(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, Tracked]]:
    for name in type(model).model_fields:
        val = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(val, Tracked):
            yield path, val
        elif isinstance(val, BaseModel):
            yield from iter_tracked(val, path)
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, BaseModel):
                    yield from iter_tracked(item, f"{path}[{i}]")

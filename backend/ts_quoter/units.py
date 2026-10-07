"""Sistema centralizado de unidades.

Regla: nunca mezclar unidades silenciosamente. Toda conversión pasa por aquí y puede
reportarse (``convert_with_trace``).

Unidades canónicas internas (decisión documentada en docs/DECISIONS.md, D-03):
    longitud  -> mm   (unidad natural de los dibujos; SI-derivada)
    área      -> m2
    volumen   -> m3
    masa      -> kg
    tiempo    -> hr   (las tarifas son por hora)
Las monedas NO se convierten aquí (ver ``money.py``).
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum


class Dimension(str, Enum):
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    MASS = "mass"
    TIME = "time"
    COUNT = "count"
    RATIO = "ratio"


D = Decimal

# factor relativo de cada unidad dentro de su dimensión (convert = valor × f_origen / f_destino)
_UNITS: dict[str, tuple[Dimension, Decimal]] = {
    # length -> mm
    "um": (Dimension.LENGTH, D("0.001")),
    "mm": (Dimension.LENGTH, D("1")),
    "cm": (Dimension.LENGTH, D("10")),
    "m": (Dimension.LENGTH, D("1000")),
    "inch": (Dimension.LENGTH, D("25.4")),
    "in": (Dimension.LENGTH, D("25.4")),
    "ft": (Dimension.LENGTH, D("304.8")),
    # area -> m2
    "mm2": (Dimension.AREA, D("0.000001")),
    "cm2": (Dimension.AREA, D("0.0001")),
    "m2": (Dimension.AREA, D("1")),
    "in2": (Dimension.AREA, D("0.00064516")),
    # volume -> m3
    "mm3": (Dimension.VOLUME, D("1E-9")),
    "cm3": (Dimension.VOLUME, D("0.000001")),
    "m3": (Dimension.VOLUME, D("1")),
    "in3": (Dimension.VOLUME, D("0.000016387064")),
    # mass -> kg
    "kg": (Dimension.MASS, D("1")),
    "g": (Dimension.MASS, D("0.001")),
    "lb": (Dimension.MASS, D("0.45359237")),
    # time -> hr
    # (factores relativos en segundos para que la conversión sea exacta; la unidad canónica sigue siendo hr)
    "hr": (Dimension.TIME, D("3600")),
    "h": (Dimension.TIME, D("3600")),
    "min": (Dimension.TIME, D("60")),
    "s": (Dimension.TIME, D("1")),
    # misc
    "pcs": (Dimension.COUNT, D("1")),
    "ea": (Dimension.COUNT, D("1")),
    "%": (Dimension.RATIO, D("0.01")),
    "ratio": (Dimension.RATIO, D("1")),
}

# alias de texto libre -> símbolo canónico (se conserva raw_value fuera de aquí)
_ALIASES = {
    "µm": "um", "mm²": "mm2", "cm²": "cm2", "m²": "m2", "in²": "in2",
    "mm³": "mm3", "cm³": "cm3", "m³": "m3", "in³": "in3",
    '"': "inch", "pulg": "inch", "pulgada": "inch", "pulgadas": "inch", "inches": "inch",
    "feet": "ft", "pie": "ft", "pies": "ft",
    "kgs": "kg", "lbs": "lb", "hrs": "hr", "hora": "hr", "horas": "hr", "minutos": "min",
    "pza": "pcs", "pzas": "pcs", "pieza": "pcs", "piezas": "pcs",
}

CANONICAL = {
    Dimension.LENGTH: "mm",
    Dimension.AREA: "m2",
    Dimension.VOLUME: "m3",
    Dimension.MASS: "kg",
    Dimension.TIME: "hr",
    Dimension.COUNT: "pcs",
    Dimension.RATIO: "ratio",
}


class UnitError(ValueError):
    """Unidad desconocida o conversión entre dimensiones incompatibles."""


def normalize_unit(unit: str) -> str:
    u = unit.strip()
    u = _ALIASES.get(u, _ALIASES.get(u.lower(), u))
    if u not in _UNITS and u.lower() in _UNITS:
        u = u.lower()
    if u not in _UNITS:
        raise UnitError(f"Unidad no soportada: '{unit}'")
    return u


def dimension_of(unit: str) -> Dimension:
    return _UNITS[normalize_unit(unit)][0]


def convert(value: Decimal | float | int, from_unit: str, to_unit: str) -> Decimal:
    """Convierte ``value`` de ``from_unit`` a ``to_unit``. Falla si las dimensiones difieren."""
    fu, tu = normalize_unit(from_unit), normalize_unit(to_unit)
    fdim, ffac = _UNITS[fu]
    tdim, tfac = _UNITS[tu]
    if fdim != tdim:
        raise UnitError(f"No se puede convertir {fdim.value} ({from_unit}) a {tdim.value} ({to_unit})")
    return D(str(value)) * ffac / tfac


def to_canonical(value: Decimal | float | int, unit: str) -> tuple[Decimal, str]:
    dim = dimension_of(unit)
    target = CANONICAL[dim]
    return convert(value, unit, target), target


def convert_with_trace(value: Decimal | float | int, from_unit: str, to_unit: str) -> dict:
    """Conversión con registro para mostrar al usuario."""
    result = convert(value, from_unit, to_unit)
    return {"original_value": str(value), "original_unit": from_unit, "converted_value": str(result), "converted_unit": to_unit}

"""Dinero: conversión de moneda trazable y recencia de precios. Todo en Decimal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .rules.loader import RuleSet
from .schemas.cost_master import CostMaster, FxRate

ZERO = Decimal("0")
ONE = Decimal("1")


class MissingFxError(LookupError):
    pass


@dataclass(frozen=True)
class FxConversion:
    original_currency: str
    original_value: Decimal
    fx_rate: Decimal
    fx_source: str
    fx_date: Optional[date]
    converted_value: Decimal
    policy: str


def find_fx(master: CostMaster, base: str, quote: str) -> tuple[Optional[FxRate], bool]:
    """Devuelve (registro, invertido)."""
    for r in master.fx:
        if r.base == base and r.quote == quote:
            return r, False
        if r.base == quote and r.quote == base:
            return r, True
    return None, False


def convert_money(amount: Decimal, from_ccy: str, to_ccy: str, master: CostMaster, rules: RuleSet) -> FxConversion:
    """Convierte con la política FX del rule set (reference/current/protected). Nunca silencioso."""
    policy = str(rules.get("money.fx_policy"))
    if from_ccy == to_ccy:
        return FxConversion(from_ccy, amount, ONE, "identity", None, amount, policy)
    rec, inverted = find_fx(master, from_ccy, to_ccy)
    if rec is None:
        raise MissingFxError(f"No hay tipo de cambio {from_ccy}->{to_ccy} en Cost Master {master.version}")
    rate = getattr(rec, policy)
    eff = (ONE / rate) if inverted else rate
    return FxConversion(from_ccy, amount, eff, f"{rec.fx_source} ({policy})", rec.fx_date, amount * eff, policy)


def recency(price_date: Optional[date], as_of: date, rules: RuleSet) -> tuple[Optional[int], str]:
    if price_date is None:
        return None, "obsolete"
    age = (as_of - price_date).days
    if age <= int(rules.get("price_recency_days.fresh")):
        return age, "fresh"
    if age <= int(rules.get("price_recency_days.acceptable")):
        return age, "acceptable"
    if age <= int(rules.get("price_recency_days.stale")):
        return age, "stale"
    return age, "obsolete"


def q2(x: Decimal) -> Decimal:
    """Redondeo de presentación a centavos (el cálculo interno no se redondea)."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_commercial(x: Decimal, mode: str, step: Decimal) -> Decimal:
    if mode == "none" or step <= 0:
        return q2(x)
    if mode == "nearest":
        return (x / step).quantize(ONE, rounding=ROUND_HALF_UP) * step
    if mode == "up":
        n = (x / step).to_integral_value(rounding="ROUND_CEILING")
        return n * step
    raise ValueError(f"modo de redondeo no soportado: {mode}")

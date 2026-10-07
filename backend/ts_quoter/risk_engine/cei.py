"""Cost Estimation Index (0–100). La confianza de la IA NO se usa sola: se combina con reglas objetivas."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from ..schemas.common import SourceStatus
from ..schemas.results import CEIComponent, CategoryRisk, LineStatus
from ..schemas.walk import iter_tracked

if TYPE_CHECKING:
    from .engine import RiskInputs

ZERO, ONE, HUNDRED = Decimal("0"), Decimal("1"), Decimal("100")

STATUS_SCORE = {
    SourceStatus.EXPLICIT: Decimal("1.0"),
    SourceStatus.USER_CONFIRMED: Decimal("1.0"),
    SourceStatus.DERIVED: Decimal("0.95"),
    SourceStatus.DEFAULTED: Decimal("0.6"),
    SourceStatus.INFERRED: Decimal("0.6"),  # × confianza
}


def compute_cei(x: "RiskInputs", cats: dict[str, CategoryRisk]) -> tuple[Decimal, str, list[CEIComponent]]:
    r = x.rules
    w = r.get("cei.weights")
    comps: list[CEIComponent] = []

    # 1. calidad de interpretación: campos con información, ponderados por estatus; penaliza críticos desconocidos
    known = [(p, t) for p, t in iter_tracked(x.job) if t.source_status not in (SourceStatus.UNKNOWN,)]
    scores = []
    for _, t in known:
        if t.source_status == SourceStatus.CONFLICTING:
            scores.append(ZERO)
        elif t.source_status == SourceStatus.INFERRED:
            scores.append(STATUS_SCORE[t.source_status] + Decimal("0.4") * Decimal(str(t.confidence)))
        else:
            scores.append(STATUS_SCORE[t.source_status])
    base = (sum(scores, ZERO) / len(scores)) if scores else ZERO
    critical_unknown = len([rv for rv in x.reviews if rv.severity.value in ("HIGH", "CRITICAL")])
    penalty = min(Decimal("0.6"), Decimal(critical_unknown) * Decimal("0.08"))
    iq = (base * (ONE - penalty) * HUNDRED).quantize(Decimal("0.1"))
    comps.append(CEIComponent(name="interpretation_quality", score=iq, weight=w["interpretation_quality"],
                              explanation=f"{len(known)} campos con información, calidad media {base:.2f}; {critical_unknown} alertas HIGH/CRITICAL (−{penalty * 100:.0f}%)"))

    # 2. calidad de fuente de costo: nivel A–E con penalización por antigüedad
    ls, rp = r.get("cei.level_score"), r.get("cei.recency_penalty")
    src_scores = []
    for s in x.mat_sources:
        src_scores.append(Decimal(ls[s.level]) - Decimal(rp.get(s.recency or "obsolete", 0)))
    n_missing_price = len([l for l in x.missing if l.category in ("material", "buy_component")])
    src_scores += [ZERO] * n_missing_price
    csq = (sum(src_scores, ZERO) / len(src_scores)).quantize(Decimal("0.1")) if src_scores else Decimal("50")
    comps.append(CEIComponent(name="cost_source_quality", score=max(ZERO, csq), weight=w["cost_source_quality"],
                              explanation=f"{len(x.mat_sources)} precios de material (niveles {sorted({s.level for s in x.mat_sources})}), {n_missing_price} faltantes"))

    # 3. similitud histórica (no disponible en MVP -> neutro configurable, explícito)
    hs = Decimal(r.get("cei.historical_similarity_default"))
    comps.append(CEIComponent(name="historical_similarity", score=hs, weight=w["historical_similarity"],
                              explanation="sin módulo de similitud (fase 9): valor neutro de regla"))

    # 4. confianza de procesos
    pconf = [Decimal(str(p.confidence)) for c in x.comps for p in c.processes]
    pc = ((sum(pconf, ZERO) / len(pconf)) * HUNDRED).quantize(Decimal("0.1")) if pconf else Decimal("50")
    comps.append(CEIComponent(name="process_confidence", score=pc, weight=w["process_confidence"],
                              explanation=f"confianza media de {len(pconf)} procesos"))

    # 5. información faltante
    n = len(x.cost.lines)
    mi = (HUNDRED * (ONE - Decimal(len(x.missing)) / Decimal(n))).quantize(Decimal("0.1")) if n else ZERO
    comps.append(CEIComponent(name="missing_information", score=mi, weight=w["missing_information"],
                              explanation=f"{len(x.missing)}/{n} líneas sin costo"))

    # 6. novedad de fabricación
    ft = x.job.project.first_time_build
    nov = Decimal("60") if not ft.known else (Decimal("40") if ft.value else HUNDRED)
    comps.append(CEIComponent(name="manufacturing_novelty", score=nov, weight=w["manufacturing_novelty"],
                              explanation="primera fabricación" if ft.known and ft.value else ("repetido" if ft.known else "desconocido")))

    cei = sum((c.score * c.weight for c in comps), ZERO).quantize(Decimal("0.1"))
    label = "MANUAL_ESTIMATE_RECOMMENDED"
    for b in r.get("cei.bands"):
        if cei >= b["min"]:
            label = str(b["label"])
            break
    # nunca AUTOQUOTE si hay costo parcial o conflicto
    if label == "AUTOQUOTE_CANDIDATE" and (x.missing or cats["interpretation"].score > 30):
        label = "REVIEW_ALERTS_ONLY"
    return cei, label, comps

"""Guardas determinísticas post-IA (no dependen del modelo). Se aplican SIEMPRE antes de guardar.

1. 'explicit' exige cita textual verificable en la fuente; si no aparece -> se degrada a 'inferred'.
2. La IA no puede producir 'user_confirmed' ni 'defaulted' (sólo humanos y reglas internas).
3. Montos de dinero sólo si son explícitos y citados (Regla 1: la IA nunca inventa costos).
4. Confianza de 'inferred' se topa (la IA no calibra bien su propia probabilidad, sec. 12).
"""

from __future__ import annotations

import re
import unicodedata

from ..schemas.common import Impact, ReviewItem, Severity, SourceRef, SourceStatus
from ..schemas.manufacturing import ManufacturingJob
from ..schemas.walk import iter_tracked

#: datos que mueven el costo de forma gruesa: si la IA los da como explícitos sin cita, quedan unknown (no se asumen)
CRITICAL_SUFFIXES = (".side", ".sides", "material.grade", ".final_finish", "material.thickness", "project.quantity")
MONEY_SUFFIXES = ("unit_cost", "tooling_cost", "fixture_cost", "cost_per_piece", "one_time_cost", "logistics_cost")
INFERRED_CONF_CAP = 0.85
DOWNGRADED_CONF = 0.5


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("×", "x").replace("ø", "o")
    return re.sub(r"[\s\"'`.,;:]+", " ", s).strip()


def excerpt_found(excerpt: str | None, source: str) -> bool:
    if not excerpt or len(excerpt.strip()) < 2:
        return False
    return _norm(excerpt) in _norm(source)


def apply_guards(job: ManufacturingJob, source_text: str, project_paths_from_user: set[str]) -> tuple[ManufacturingJob, list[str]]:
    """Devuelve (job corregido, bitácora de correcciones). Campos capturados por el usuario no se tocan."""
    log: list[str] = []
    reviews: list[ReviewItem] = []
    n = 0

    def review(sev: Severity, path: str, desc: str, action: str) -> None:
        nonlocal n
        n += 1
        reviews.append(ReviewItem(review_id=f"G{n:03d}", severity=sev, category="ai_guard", description=desc,
                                  cost_impact=Impact.MEDIUM if sev != Severity.LOW else Impact.LOW,
                                  recommended_action=action, field_path=path))

    for path, t in iter_tracked(job):
        if path in project_paths_from_user:
            continue
        st = t.source_status
        if st == SourceStatus.USER_CONFIRMED or st == SourceStatus.DEFAULTED:
            t.source_status = SourceStatus.INFERRED
            t.confidence = min(t.confidence, DOWNGRADED_CONF)
            log.append(f"{path}: '{st.value}' no permitido desde IA → inferred")
            st = SourceStatus.INFERRED
        if st == SourceStatus.EXPLICIT:
            ex = t.source_reference.excerpt if t.source_reference else None
            if not excerpt_found(ex, source_text) and path.endswith(CRITICAL_SUFFIXES):
                proposed = getattr(t.value, "value", t.value)
                t.value = None
                t.source_status = SourceStatus.UNKNOWN
                t.confidence = 0.0
                ref = t.source_reference or SourceRef()
                ref.note = f"IA propuso '{proposed}' como explícito con cita no encontrada ({ex!r}); descartado"
                t.source_reference = ref
                log.append(f"{path}: dato crítico '{proposed}' sin cita verificable → unknown (no se asume)")
                review(Severity.HIGH, path, f"La IA afirmó {path} = {proposed} sin cita verificable; se dejó como desconocido",
                       "Confirmar contra el documento o con el cliente")
                continue
            if not excerpt_found(ex, source_text):
                t.source_status = SourceStatus.INFERRED
                t.confidence = min(t.confidence, DOWNGRADED_CONF)
                ref = t.source_reference or SourceRef()
                ref.note = ((ref.note or "") + " | cita no verificada en el texto fuente").strip(" |")
                t.source_reference = ref
                log.append(f"{path}: 'explicit' sin cita verificable ({ex!r}) → inferred")
                review(Severity.LOW, path, f"Dato marcado como explícito sin cita verificable: {path} = {getattr(t.value, 'value', t.value)}",
                       "Confirmar contra el documento")
                st = SourceStatus.INFERRED
        if st == SourceStatus.INFERRED and t.confidence > INFERRED_CONF_CAP:
            t.confidence = INFERRED_CONF_CAP
        is_money = path.endswith(MONEY_SUFFIXES) or re.search(r"^logistics\[\d+\]\.cost$", path)
        if is_money and t.value is not None and st != SourceStatus.EXPLICIT:
            log.append(f"{path}: monto {t.value} no explícito eliminado (la IA no inventa costos)")
            t.value = None
            t.source_status = SourceStatus.UNKNOWN
            t.confidence = 0.0
            review(Severity.MEDIUM, path, f"Monto propuesto por IA descartado en {path} (no explícito en la fuente)",
                   "Cargar precio desde cotización/OC o Cost Master")

    data = job.model_dump(mode="json")
    data["review_items"] = data.get("review_items", []) + [r.model_dump(mode="json") for r in reviews]
    return ManufacturingJob.model_validate(data), log

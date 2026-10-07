# Decisiones, contradicciones y supuestos peligrosos

Registro obligatorio (sec. 180, 193): toda decisión que afecta **costeo, riesgo, auditabilidad o integridad de datos**.
Ningún requisito del brief se eliminó; los diferidos están en `ROADMAP.md` con su fase.

## A. Contradicciones / ambigüedades detectadas en el brief

| # | Sección | Problema | Resolución adoptada |
|---|---|---|---|
| C-01 | 23 | "180: obsolete" es ambiguo (¿≥180 o >180?) y choca con "91–180: stale". | Límite superior **inclusivo**: 0–30 fresh, 31–90 acceptable, 91–180 stale, **>180 obsolete**. Configurable en `price_recency_days`. |
| C-02 | 55 | Las bandas de contingencia son rangos (p.ej. 7–10 %) pero el cálculo necesita un número. | Modo `global`: **interpolación lineal** dentro de la banda según la posición del score en su nivel. Determinístico y explicable. |
| C-03 | 55 vs 56 | Contingencia global y por proceso compiten. | Ambos implementados; `risk.contingency_mode` elige. Default `per_process` (el brief lo declara superior). Per-process = `base_pct[categoría] × multiplicador[nivel de riesgo global]`. |
| C-04 | 56 vs 143 vs 142 | Riesgo por proceso, contingencia de retrabajo y `risk_scrap` pueden **contar dos veces** el mismo riesgo. | Tres bolsas separadas y visibles: (1) `expected_process_scrap` sólo en material (costo base), (2) contingencia de riesgo, (3) `expected_rework_contingency` con disparadores explícitos (tolerancia cerrada, soldadura compleja, cosmético alto). Los `per_process_base_pct` de ejemplo **excluyen** retrabajo; al calibrar con datos reales hay que mantener esa disciplina. |
| C-05 | 10–11 vs 21 | "Unknown permanece unknown" vs parámetros de desperdicio/aprovechamiento que casi nunca vienen en el plano. | Distinción: un **dato técnico del producto** (material, dimensión, acabado, lados de soldadura) nunca se rellena. Un **parámetro de proceso interno** (scrap %, aprovechamiento %) puede venir de una regla versionada; queda como `defaulted` con `rule_ref` visible en la traza. |
| C-06 | 33/35 vs Regla 3 | Factores opcionales de soldadura/pulido (accesibilidad, penetración, posición) suelen faltar. Asumir "medium" sería inventar. | Si el dato falta, el factor **no se aplica** (=1.0) y se genera alerta "factor no aplicado: costo puede estar subestimado". Si el dato cambia el costo de forma gruesa (**lados** de soldadura/pulido, longitud, área, acabado final) la línea **no se costea** → Partial Cost. |
| C-07 | 17 | "Guardar en SI" vs dibujos en mm y tarifas por hora. | Unidades canónicas: **mm, m², m³, kg, hr** (SI-derivadas, naturales para el dominio). Toda conversión pasa por `units.py`; un valor sin unidad cuando se espera una es error, nunca default. |
| C-08 | 12 | La confianza de la IA no está calibrada pero el CEI la usa. | CEI combina 6 componentes; la confianza IA es sólo parte de 2 de ellos y siempre ponderada por el **estatus** del dato (explicit/derived/user_confirmed pesan más que inferred). Alertas HIGH/CRITICAL penalizan. Nunca AUTOQUOTE_CANDIDATE con costo parcial. |
| C-09 | 67 vs 66 | ¿Sobre qué base se aplica el margen? ¿Comisiones antes o después? | `precio = costo_interno_total / (1 − margen)`. Costo interno = ajustado por riesgo + overhead manufactura + overhead administrativo + costos comerciales + prima de urgencia. Costos comerciales (comisión) como % del **costo**, no del precio, para evitar circularidad; documentado en la traza. |
| C-10 | 16, 82 | Recencia de precios depende de "hoy" → el mismo cálculo cambiaría día a día. | El motor **no lee el reloj**: `as_of_date` es parámetro y se guarda con el resultado. Precios con fecha posterior a `as_of` se ignoran. Reproducibilidad exacta. |
| C-11 | 22 vs 134 | Jerarquía A–E y "nunca el más barato". | Selección: menor nivel (A mejor) → más reciente → id. El precio no participa en el orden. |
| C-12 | 25 | B "última compra reciente" vs C "histórica actualizada": frontera no definida. | B si la compra es ≤ `acceptable` días respecto a la fecha de importación; si no, C con `adjustment_factor` (si falta: 1.0 + advertencia). |
| C-13 | 24 | COST_MASTER incluye "RiskParameters", pero pesos de riesgo también son reglas versionadas. | El rule set es la fuente; la hoja RiskParameters sobreescribe pesos y queda **dentro del `cost_master_version`** del resultado, así que sigue siendo reproducible. |
| C-14 | 24 "Machines" vs "Processes" | Ambas hojas describen tarifas horarias. | Misma estructura (`rate_key`, `hourly_rate`…); ambas se fusionan en `process_rates`. |
| C-15 | 71, 48 | Empaque "por paquete" con cantidad discreta rompe la curva de precio por cantidad si se trata como costo fijo. | Empaque se prorratea por unidad (`unit_cost / units_per_package`). Redondeo hacia arriba de cajas: pendiente para fase 9. |
| C-16 | 160 | Stop conditions vs "permitir guardar análisis parcial". | Ambos: el análisis parcial se guarda y se muestra; la **recomendación** queda `BLOCKED` salvo `proceed_with_assumptions` con aprobador. |
| C-17 | 6 | Árbol de carpetas pide `/cost_engine`, `/risk_engine`… en raíz. | Viven como subpaquetes de `backend/ts_quoter/` (importables, testeables, sin hacks de `sys.path`). Carpetas raíz conservadas para lo que no es código Python (`rules`, `data`, `prompts`, `docs`, `tests`, `migrations`, `logs`, `sample_projects`, `frontend`). |
| C-18 | 172 | Seed de ejemplo vs "no inventar datos de T&S". | Todos los valores de `COST_MASTER_SAMPLE.xlsx` y del rule set `1.0.0-sample` son **ficticios** y van marcados `is_sample`. El importador rechaza archivos que mezclan sample y producción; todo resultado que toca sample lleva la advertencia "SAMPLE DATA". |

## B. Supuestos técnicamente peligrosos (vigilar)

1. **Productividades de soldadura/pulido por tabla.** Son la mayor fuente de error esperado. Se exponen como reglas y se calibrarán con el learning loop (fase 10); nunca se auto-ajustan (sec. 63).
2. **Peso de perfiles (ángulo, canal, PTR).** No hay fórmula paramétrica en MVP: requieren `net_weight` capturado o quedan como Missing Cost. Preferible a adivinar.
3. **Área de pulido** la proporciona el intérprete/usuario; el motor no calcula superficies desde CAD (fase CAD futura).
4. **Tipo de cambio**: el sample usa valores ficticios. En producción debe cargarse con fuente y fecha; la política (`protected_fx`) es editable.
5. **Min. charges** por categoría se comparan contra el total de la categoría del pedido; si un proceso se subcontrata parcialmente, revisar.
6. **SQLite + JSON**: el MCJ completo vive en JSON; las columnas proyectadas (componentes, materiales) son para búsqueda. En PostgreSQL migrar `JSON` → `JSONB`.

## C. Decisiones técnicas que no cambian comportamiento (opción más simple)

- Decimal en todo el cálculo monetario; redondeo sólo en presentación (`q2`) y en el redondeo comercial.
- Monolito modular FastAPI + SQLAlchemy 2 + Alembic (`render_as_batch` para SQLite).
- Reglas en YAML legible por ingeniería; hash SHA-256 del contenido como identidad.
- Sin vector search; similitud por metadata en fase 9.
- Frontend aún no iniciado (sec. 111, 187): la API cubre el demo 1 completo.

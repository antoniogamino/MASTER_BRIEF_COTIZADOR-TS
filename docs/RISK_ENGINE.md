# Risk Engine

Independiente del margen (Regla 7) y de la contingencia comercial (Regla 8). Entrada: MCJ + `CostResult` + Cost Master + reglas.

## Categorías y factores

Cada factor activado aporta `peso × severidad(0–1)` puntos; la categoría topa en 100. Cada **driver** guarda la evidencia concreta:

```
manufacturing   first_time_build   +15.00  primera fabricación
manufacturing   tight_tolerance    + 9.00  tolerancia más cerrada ±0.1 mm
cost_data       old_material_price +15.00  precio de material viejo (stale)
```

| Categoría | Factores implementados |
|---|---|
| interpretation | missing_dimensions, ambiguous_welds, missing_material, missing_finish, conflicts, low_ai_confidence, poor_drawing_quality, missing_pages, unreadable_notes, multiple_revisions, unclear_units, unclear_quantity |
| manufacturing | first_time_build, tight_tolerance, high_weld_density, sanitary_requirement, manual_finishing, difficult_access, small_precision_part, custom_fixture, unknown_process_time, large_part |
| cost_data | old_material_price, parametric_cost_only, estimated_machine_rate, missing_cost, foreign_currency, unknown_consumables |
| commercial | long_validity_period, export, imported_component, freight_uncertainty, small_quantity, expedite, foreign_currency_exposure |
| delivery | expedite, long_supplier_lead, first_time_build |

Pendientes (requieren datos que el MVP aún no captura): complex_geometry, distortion_risk, new_process, volatile_material, customer_change_history, single_supplier, high_scrap_risk. Están reservados en el diseño; agregarlos = evaluador + peso en reglas.

Pesos y umbrales: `risk.factors`, `risk.thresholds` (reglas) y overrides por `COST_MASTER > RiskParameters`.

## Score global y niveles

`overall = Σ score_categoría × peso_categoría` (pesos en reglas). Niveles por banda: VERY_LOW ≤15 < LOW ≤30 < MEDIUM ≤50 < HIGH ≤70 < VERY_HIGH.

## Contingencia

- **per_process** (default): por categoría de costo, `base_pct[categoría] × multiplicador[nivel global]` (p.ej. soldadura 15 %, pulido 20 %, material 3 %).
- **global**: banda del nivel (p.ej. MEDIUM 7–10 %) interpolada linealmente según el score.
- **Retrabajo** (bolsa separada): tolerancia ≤ 0.1 mm → % sobre maquinado; penetración completa o sanitario → % sobre soldadura; #8 / Ra ≤ 0.6 → % sobre pulido.

Se muestran siempre: Base cost · Risk contingency · Rework contingency · Risk-adjusted cost (nunca escondida en el costo base).

## CEI (Cost Estimation Index 0–100)

| Componente | Cálculo |
|---|---|
| interpretation_quality | calidad media por estatus de campos con información (inferred ponderado por confianza), penalizada por alertas HIGH/CRITICAL |
| cost_source_quality | nivel A=100 … D=40, E=0, menos penalización por antigüedad |
| historical_similarity | neutro (50) hasta fase 9 — marcado "no disponible" |
| process_confidence | confianza media de procesos |
| missing_information | 100 × (1 − líneas faltantes / líneas) |
| manufacturing_novelty | repetido 100 · desconocido 60 · primera vez 40 |

Clasificación: ≥85 AUTOQUOTE_CANDIDATE · ≥70 REVIEW_ALERTS_ONLY · ≥50 ENGINEERING_REVIEW · <50 MANUAL_ESTIMATE_RECOMMENDED. Nunca AUTOQUOTE_CANDIDATE con costo parcial o riesgo de interpretación >30. **No existe** AUTOQUOTE_SENT.

## Pendiente (fase 10)

Sesgo histórico por proceso (p.ej. "soldadura subestimada 18 %") como factor propuesto → ajuste recomendado → aprobación humana → nueva versión de reglas.

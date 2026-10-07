# Modelo de dominio

## Separación epistemológica (principio fundamental)

| Nivel | Dónde vive | Quién lo produce |
|---|---|---|
| Hechos | `Tracked.source_status = explicit` + `source_reference` (doc, página, región) | documento |
| Interpretación / inferencia | `inferred` + `confidence` | IA o estimador |
| Cálculo | `derived` (en MCJ) o `CostLine.inputs` con `derived:` | fórmula |
| Regla interna | `defaulted` + `rule_ref` | rule set versionado |
| Riesgo | `RiskResult` (drivers con evidencia) | Risk Engine |
| Decisión comercial | `CommercialInputs` (margen, proceed_with_assumptions) + `approved_price` | humano |

Estados de información: `explicit · inferred · derived · defaulted · unknown · conflicting · user_confirmed`.
Invariantes (validadas por Pydantic): `unknown` ⇒ sin valor; cualquier otro (salvo `conflicting`) ⇒ con valor; `defaulted` ⇒ `rule_ref`.

## Entidades principales

- **Project** — identidad, cliente, plano, revisión, cantidad, moneda, destino, exportación, vigencia, urgencia, primera fabricación, estatus (draft → interpreting → requires_review → costing → ready_for_approval → approved → quoted → won/lost → completed/archived; + failed_interpretation).
- **SourceDocument** — checksum SHA-256, tipo de fuente, `sent_to_ai` (transparencia). Original inmutable.
- **Component** — `make_or_buy` (MAKE/BUY/UNKNOWN), `parent_component_id` + `quantity_per_parent` (roll-up de ensambles; distinto de la cantidad cotizada), material propio (nunca global), geometría, tolerancias con valor real, ruta de procesos ordenable (`routing_sequence`), info de compra.
- **Material** — grado (normalizado + raw), forma, espesor/calibre/OD/ID/pared, peso neto opcional, parámetros de aprovechamiento. Peso: **neto → consumido → comprado** (tres valores).
- **Process** (unión discriminada por `process_type`): `laser_cutting`, `bending`, `rolling`, `welding` (con `WeldJoint[]`), `surface_polishing`, `weld_finishing`, `machining`, `outsourcing`, y genéricos por tiempo (`passivation`, `inspection`, `assembly`, `saw_cutting`, `drilling`, `tapping`, `electropolishing`, … y `unknown`). Todos aceptan overrides de setup/run auditables.
- **WeldJoint** — proceso, tipo de junta, longitud, tamaño, **lado (one_side/both_sides/unknown)**, continuidad, penetración, purga, sanitario, accesibilidad, posición, acabado post-soldadura.
- **QualityRequirement / PackagingItem / LogisticsItem** — estado `required · not_required · unknown · inferred` (exportación NO agrega costos automáticamente).
- **Engineering** — horas ingeniería/CAD/programación/planeación (unknown ⇒ alerta, nunca cero implícito), fixtures (NRE o amortizados).
- **Conflict / Uncertainty / Assumption** — visibles siempre; una suposición tiene razón, impacto en costo y riesgo, y aprobador.
- **Override** — `original_value`, `new_value`, `changed_by`, `changed_at`, `reason`. Cada override crea nueva `interpretation_version`.

## Cost Master

`MaterialPrice` (nivel A–D, fecha, proveedor, referencia OC/cotización, `adjustment_factor`, `possible_outlier`, `is_sample`), `ProcessRate` (tarifa horaria, tipo, cargo mínimo, `estimated`), `LaborRate` (directo vs **fully burdened**), `SimpleCostItem` (consumibles, empaque, calidad, logística), `FxRate` (reference / current / protected), `RiskParameterOverride`.

## Resultados

`CostLine`: categoría, estado (`complete`/`missing`), `one_time` (setup/NRE) y `per_unit`, horas, cantidades (net/consumed/purchased kg…), **fórmula, insumos con fuente, fuentes monetarias, reglas**. `CostResult` agrega cobertura y `review_items`. `RiskResult` y `QuoteRecommendation` ver `RISK_ENGINE.md` y `COST_ENGINE.md`.

## Base de datos (tablas)

`users, projects, project_revisions, documents, interpretations, components, materials, processes, cost_sources (versiones de Cost Master), cost_results, risk_results, rules, rule_versions, suppliers, purchase_history, quotes, actual_costs, audit_log`. Soft delete (`deleted_at`) en entidades editables. Migración inicial en `migrations/versions/`.

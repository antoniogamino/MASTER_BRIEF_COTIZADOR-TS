# Roadmap

Cada hito deja la aplicación ejecutable y con tests en verde.

| Fase | Contenido | Estado |
|---|---|---|
| 0 Setup | repo, estructura, README, .env.example, Dockerfile, Alembic, docs | ✅ |
| 1 Dominio | MCJ (`Tracked[T]`), Cost Master, resultados, JSON Schema exportado, overrides auditables | ✅ |
| 2 Cost Engine | material, láser, doblez, rolado, soldadura + consumibles, pulido, acabado de soldadura, maquinado, genéricos, subcontrato, BUY, calidad, empaque, logística, ingeniería/NRE/fixtures, roll-up, cobertura, cargos mínimos | ✅ |
| 3 Cost Master | importador COST_MASTER.xlsx + HISTORICAL_PURCHASES.xlsx con validación, alias, outliers, duplicados, bloqueo sample/producción | ✅ |
| 8 (adelantado) Risk + Commercial | 5 categorías, CEI, contingencia global/per-process, retrabajo, margen real, cortes de cantidad, stop conditions, approval gates | ✅ (versión inicial) |
| **Demo 1** | Crear proyecto → MCJ manual → tarifas Excel → costo → riesgo → margen → precio → traza (`tsq demo`, API) | ✅ |
| 4 Text Interpreter | prompt `text/v1`, proveedor Anthropic (salida estructurada), merge con proyecto (discrepancias → conflict), guardas anti-alucinación, reparación controlada, `interpreted.json`, log IA, `tsq text`, `POST /projects/{p}/interpret/text`, ReplayProvider | ✅ (falta calibrar prompt con RFQs reales) |
| 5 Drawing Interpreter | PDF multipágina, rasterizado, title block, notas, BOM, material/espesor/acabado/tolerancias; `source_reference` por página/región; drawing_quality_score | |
| 6 Hybrid | fusión dibujo + texto, detección de coincidencias / contradicciones → `conflicts[]` | |
| 7 Review UI | React/Next: visor de documento + panel estructurado (tabs Overview…Audit), REQUIRES REVIEW priorizado, edición inline → override, "Explain calculation", dashboard mínimo | |
| 9 History | comparación REV A vs REV B (técnica + económica), change impact, proyectos similares por metadata, export PDF | |
| 10 Learning loop | estimado vs real, error absoluto/%/sesgo por proceso, ajustes recomendados con aprobación (nunca automáticos) | |
| Futuro | Odoo (lectura → borrador), FX/inflación/índices, DXF/STEP (bounding box, área, masa), highlight de región en dibujo, perfiles de cliente, capacidad/rush | |

## Prohibido en MVP (sec. 122)
Envío automático de correos/cotizaciones, escritura en Odoo, OCs automáticas, aprendizaje sin aprobación, precio sin revisión, CAD 3D completo, FEA, nesting optimizado, scheduling.

## Siguiente paso inmediato
0. Correr `tsq text` con 5–10 RFQs reales y guardar cada salida como golden case (prompt v1 → v2).
1. Calibrar con 3–5 cotizaciones reales recientes de T&S → primeros golden cases reales y `rules/default_rules_v2.yaml` (no sample).
2. Cargar COST_MASTER real (tarifas cargadas, precios A/B vigentes, FX con fuente).
3. Text Interpreter con el ejemplo "Charola AISI 304 de 500 x 300 x 100, esquinas soldadas, acabado #4".

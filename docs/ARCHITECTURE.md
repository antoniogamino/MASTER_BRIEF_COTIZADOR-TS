# Arquitectura

Monolito modular local. Responde tres preguntas: **¿qué hay que fabricar? ¿cuánto cuesta? ¿qué tan probable es que estemos equivocados?**

```
INPUT (texto / PDF / imagen)                         ← fases 4-6
  → FACT EXTRACTION → TECHNICAL INTERPRETATION → MANUFACTURING INFERENCE   (IA, interpreters/)
  → Manufacturing Cost JSON (MCJ) validado (Pydantic, schemas/)
  → HUMAN REVIEW (sólo excepciones: review_items, overrides auditables)
  → COST ENGINE (determinístico, sin IA)       cost_engine/ + material_engine/ + process_engine/ + packaging_engine/
  → RISK ENGINE (independiente del margen)     risk_engine/ (drivers + CEI)
  → COMMERCIAL ENGINE (margen real, redondeo)  commercial_engine/
  → QUOTE RECOMMENDATION (nunca envío automático)
```

**La IA interpreta. El motor calcula. El riesgo protege. El humano valida excepciones.**

## Capas

| Capa | Paquete | Responsabilidad | Depende de |
|---|---|---|---|
| Dominio | `schemas/` | MCJ, Cost Master, resultados, `Tracked[T]` (value + source_status + confidence + source_reference + raw_value) | — |
| Unidades / dinero | `units.py`, `money.py` | conversiones exactas, FX con política, recencia | rules |
| Reglas | `rules/loader.py` + `/rules/*.yaml` | parámetros versionados con hash | — |
| Cálculo | `cost_engine/`, `material_engine/`, `process_engine/`, `packaging_engine/` | líneas de costo con fórmula, insumos, fuentes y reglas | dominio, reglas, Cost Master |
| Riesgo | `risk_engine/` | 5 categorías, drivers con evidencia, contingencia, retrabajo, CEI | resultado de costo |
| Comercial | `commercial_engine/` | overheads, margen, markup informativo, cortes por cantidad, stop conditions, approval gates | costo + riesgo |
| Orquestación | `pipeline.py` | produce validated/costing/risk/quote_summary/audit.json | todo lo anterior |
| Datos | `importers/`, `exporters/`, `db/` | Excel ↔ Cost Master, reporte Excel interno, SQLAlchemy + Alembic | dominio |
| Interfaces | `api/` (FastAPI), `cli.py` | endpoints locales y CLI | pipeline, db |
| IA (contrato) | `interpreters/`, `providers/` | `ManufacturingInterpreter`, `AIProvider`, FX/inflación/índices, Odoo | dominio |

Regla de dependencia: **los motores nunca importan `interpreters/`, `providers/`, `api/` ni `db/`.** Por eso el costeo funciona offline (sec. 126) y es reproducible.

## Estructura de directorios

```
ts-cotizador/
├── backend/ts_quoter/
│   ├── schemas/          common.py (Tracked, ReviewItem) · manufacturing.py (MCJ) · cost_master.py · results.py · overrides.py · walk.py
│   ├── cost_engine/      engine.py (calculate, roll-up, coverage, minimum charges) · context.py (traza)
│   ├── material_engine/  material.py (peso neto→consumido→comprado, jerarquía A–E) · normalize.py (alias)
│   ├── process_engine/   forming.py (láser, doblez, rolado) · welding.py · finishing.py (pulido ≠ acabado de soldadura) · machining.py (maquinado, genéricos, subcontrato)
│   ├── packaging_engine/ packaging.py (empaque, calidad, logística, BUY, ingeniería/NRE, fixtures)
│   ├── risk_engine/      engine.py (factores) · cei.py
│   ├── commercial_engine/engine.py
│   ├── importers/        excel.py (COST_MASTER, HISTORICAL_PURCHASES)
│   ├── exporters/        excel_summary.py (Internal Costing Report)
│   ├── interpreters/     base.py + text/ drawing/ hybrid/   (fases 4-6)
│   ├── providers/        base.py (AIProvider, ExchangeRate, Inflation, MaterialIndex, OdooGateway)
│   ├── db/               models.py · repository.py
│   ├── api/              main.py
│   ├── units.py · money.py · config.py · pipeline.py · cli.py
├── rules/                default_rules_v1.yaml (SAMPLE)
├── data/sample/          COST_MASTER_SAMPLE.xlsx · HISTORICAL_PURCHASES_SAMPLE.xlsx (generados, SAMPLE)
├── data/projects/        almacenamiento de originales (inmutables, sólo lectura)
├── sample_projects/      charola_304_demo.json (+ out/)
├── tests/                unit, integración API, import, riesgo, golden/
├── migrations/           Alembic
├── prompts/              prompts versionados (fase 4+)
├── docs/                 esta documentación + schema/*.schema.json
├── scripts/              make_sample_data.py · export_schema.py · regression.py · backup.sh
├── frontend/             (fase 7)
└── logs/
```

## Versionado e inmutabilidad

Cada resultado guarda: `schema_version`, `engine_version`, `risk_model_version`, `rule_set_ref` (`rules@<versión>#<hash>`), `cost_master_version` (hash del Excel), `interpretation_version`, `input_hash`, `as_of_date`. Interpretaciones, Cost Masters y resultados son **filas nuevas**, nunca UPDATE. Una cotización guardada no cambia cuando cambian reglas o tarifas.

## Logging (separado, sec. 80)

`logs/app.log`, `logs/ai.log` (modelo, prompt_version, input/output hash — nunca API keys), `logs/calc.log`, `logs/error.log`. La API key sólo se lee de entorno en el momento de uso (`Settings.ai_api_key()`), no vive en objetos que puedan imprimirse.

## Evolución prevista

SQLite → PostgreSQL (misma ORM; `JSON`→`JSONB`). Filesystem → object storage detrás de `repository.store_document`. Proveedores IA intercambiables vía `AIProvider`. Nada de microservicios.

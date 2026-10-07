# T&S Cotizador — sistema experto de estimación (MVP, hito 1)

Aplicación web local, modular y auditable para estimar el costo de **productos especiales de acero inoxidable** de Technology & Steel: transforma la interpretación técnica (material, procesos, soldadura, acabados, calidad, empaque) en un cálculo **determinístico y trazable**, con riesgo y contingencia separados del margen.

> No es ERP, no sustituye Odoo, no envía cotizaciones. La IA interpreta; el motor calcula; el humano valida excepciones.

**Estado:** Demo 1 (captura manual → costo → riesgo → precio → traza) y Demo 2 (texto del cliente → IA → MCJ → revisión → costo). Dibujo, híbrido y UI son las fases siguientes (`docs/ROADMAP.md`).

⚠️ Todas las tarifas, precios y reglas incluidas son **SAMPLE DATA ficticia**. No usar para cotizar hasta cargar datos reales.

## Requisitos
Python ≥ 3.11. (Opcional: Docker.)

## Instalar
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
python scripts/make_sample_data.py                      # genera data/sample/*.xlsx (SAMPLE)
alembic upgrade head                                    # crea data/tsq.db
```

## Ejecutar
```bash
tsq demo                                     # Demo 1 en consola + archivos en sample_projects/out/DEMO-0001/
tsq explain sample_projects/out/DEMO-0001/costing.json L0008     # "Explain calculation" de una línea
tsq calc mi_proyecto.json --master COST_MASTER.xlsx --as-of 2026-10-06 --out salida/
tsq import-master COST_MASTER.xlsx           # sólo validar un Excel (reporte imported/skipped/warnings/errors)

uvicorn ts_quoter.api.main:app --reload      # API local → http://127.0.0.1:8000/docs
```
Flujo API: `POST /projects` → `POST /cost-master/import` (xlsx) → `POST /projects/{p}/interpretations` (MCJ) → `POST /projects/{p}/calculate` → `GET /projects/{p}/results/{v}/explain/{line}` → `POST /projects/{p}/overrides` → recalcular → `GET /projects/{p}/audit`.

Salidas por proyecto: `validated.json`, `costing.json`, `risk.json`, `quote_summary.json`, `audit.json`, `internal_costing_report.xlsx` (uso interno).

## Interpretar con IA (fase 4)
En `.env`: `TSQ_AI_PROVIDER=anthropic`, `TSQ_AI_API_KEY=...`, `TSQ_AI_TEXT_MODEL=<id de modelo>`. Luego:
```bash
tsq text --file rfq.txt --qty 10 --currency MXN --master data/sample/COST_MASTER_SAMPLE.xlsx --out salida/
```
Escribe `interpreted.json` + costeo. Ver `docs/INTERPRETERS.md`.

## Probar
```bash
pytest -q                          # 52 tests
python scripts/regression.py       # cambios vs golden cases
```

## Datos propios
1. Copiar `data/sample/COST_MASTER_SAMPLE.xlsx`, borrar filas de ejemplo, capturar tarifas/precios reales con `is_sample` vacío (ver `docs/DATA_IMPORT.md`).
2. Copiar `rules/default_rules_v1.yaml` → `default_rules_v2.yaml`, calibrar, quitar `is_sample`, apuntar `TSQ_RULES_PATH`.
3. Capturar un proyecto como `sample_projects/charola_304_demo.json` (esquema en `docs/MANUFACTURING_JSON.md`).

## Backup (SQLite)
`scripts/backup.sh [destino]` — copia consistente de la BD, originales de proyectos y reglas. Programar diario.

## Documentación
`docs/ARCHITECTURE.md` · `DOMAIN_MODEL.md` · `MANUFACTURING_JSON.md` · `COST_ENGINE.md` · `RISK_ENGINE.md` · `INTERPRETERS.md` · `DATA_IMPORT.md` · `RULES.md` · `TESTING.md` · `ROADMAP.md` · `SECURITY.md` · **`DECISIONS.md`** (contradicciones del brief y cómo se resolvieron) · `schema/*.schema.json`.

## Reglas absolutas
1 IA nunca inventa costos · 2 inferencia ≠ hecho · 3 unknown permanece unknown · 4 conflictos visibles · 5 cálculo determinístico · 6 todo número trazable · 7 riesgo ≠ margen · 8 contingencia ≠ margen · 9 histórico nunca se sobreescribe · 10 documentos del cliente inmutables · 11 overrides auditables · 12 sin compromiso comercial autónomo.

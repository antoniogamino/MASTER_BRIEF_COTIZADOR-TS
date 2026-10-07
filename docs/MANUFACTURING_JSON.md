# Manufacturing Cost JSON (MCJ) — `mcj/1.0.0`

Esquema formal: `docs/schema/manufacturing_job.schema.json` (regenerar con `python scripts/export_schema.py`).
Ejemplo completo: `sample_projects/charola_304_demo.json`.

## Raíz

| Campo | Contenido |
|---|---|
| `schema_version` | `mcj/1.0.0` |
| `project` | identidad y variables comerciales (cantidad, moneda, destino, export, vigencia, rush, first_time_build) |
| `source_documents[]` | documentos con checksum, tipo y `sent_to_ai` |
| `customer_requirements[]` | requisitos textuales crudos |
| `components[]` | árbol de ensamble (padre + `quantity_per_parent`); MAKE/BUY/UNKNOWN; material; geometría; tolerancias; `processes[]`; `buy` |
| `quality_requirements[]` | ítems de calidad con estado y base (por lote / por pieza) |
| `packaging_requirements` | tipo de empaque + ítems (bolsa, desecante, NIMF-15…) con estado |
| `logistics[]` | flete, seguro, aduana… con estado y costo |
| `engineering` | horas de ingeniería/CAD/programación/planeación + fixtures |
| `uncertainties[]` · `conflicts[]` · `assumptions[]` | epistemología explícita |
| `interpretation_quality` | calidad del documento ≠ confianza de interpretación; intérprete, modelo, prompt_version |
| `commercial_inputs` | margen objetivo (humano), proceed_with_assumptions + aprobador, cortes de cantidad |
| `review_items[]` | alertas generadas por el intérprete |
| `audit` | `interpretation_version`, overrides |

Los resultados (`cost_summary`, `risk`, `commercial_summary`) **no** viven dentro del MCJ: son artefactos separados y versionados (`costing.json`, `risk.json`, `quote_summary.json`) para que una interpretación pueda recalcularse sin mutarse.

## Campo rastreable `Tracked[T]`

```json
"thickness": {
  "value": 1.5, "unit": "mm",
  "source_status": "explicit", "confidence": 1.0,
  "source_reference": {"document_id": "DOC-1", "page": 1, "region": "title_block", "excerpt": "CAL 16 (1.5 mm)"},
  "raw_value": "cal. 16"
}
```

- `unknown`: `{"value": null, "source_status": "unknown", "confidence": 0}` — el motor **no** lo rellena.
- `conflicting`: valor opcional; debe existir un objeto en `conflicts[]` con ambas fuentes.
- `defaulted`: requiere `source_reference.rule_ref`.
- Campos no definidos en el esquema se **rechazan** (`extra="forbid"`) → protege contra campos alucinados.

## Ejemplo de conflicto (sec. 9)

```json
"conflicts": [{
  "conflict_id": "K1",
  "field_path": "components[2].material.grade",
  "values": [
    {"value": "AISI 316L", "source_reference": {"document_id": "DOC-1", "page": 1, "region": "NOTE 4"}},
    {"value": "AISI 304",  "source_reference": {"document_id": "DOC-2", "excerpt": "Reinforcement plates may be 304."}}
  ],
  "description": "Plano especifica 316L; correo del cliente permite 304 en placas de refuerzo"
}]
```
Resultado: alerta CRITICAL, recomendación `BLOCKED` hasta resolver o aprobar suposición.

## Procesos: campos clave

| process_type | requeridos para costear | opcionales (factor no aplicado si faltan) |
|---|---|---|
| laser_cutting | `cut_length`, espesor del material | `pierce_count` |
| bending | `number_of_bends` | espesor, bounding box, `handling_complexity` |
| welding (por junta) | `weld_length`, **`side`** | accesibilidad, penetración, purga, sanitario, posición, continuidad |
| surface_polishing | `area`, **`sides`**, **`final_finish`** | accesibilidad, `geometry_type` |
| weld_finishing | `weld_length`, **`sides`** | accesibilidad, `ra_requirement_um` |
| machining | `cycle_time` | `setup_time` (alerta si falta), tolerancias, tooling |
| genéricos | `setup_time` o `run_time` | handling, inspection |
| outsourcing | `cost_per_piece` (cotización) | one_time, logística |

Cualquier proceso acepta `setup_time_override` / `run_time_override` (horas) que sustituyen el modelo paramétrico y quedan en la traza.

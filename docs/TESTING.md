# Testing

```
pytest -q                       # 52 tests: unidades, esquema, motor, riesgo, comercial, import, overrides, API, golden
python scripts/regression.py    # diferencia contra golden cases (tras cambiar prompt/modelo/reglas/código)
```

- `tests/test_units_schema.py` — conversiones exactas, invariantes de `Tracked`, campos alucinados, duplicados, ciclos.
- `tests/test_cost_engine.py` — material neto/consumido/comprado verificado a mano, jerarquía A–E, alias, determinismo, no mutación, no-asunciones (lado de soldadura, 304, #4), Partial Cost, pulgadas=mm, roll-up, FX, setup vs run, trazabilidad total.
- `tests/test_risk_commercial.py` — drivers con evidencia, margen real, contingencia independiente del margen, bandas, precio unitario decreciente, stop conditions, proceed-with-assumptions, conflicto de material, nunca AUTOQUOTE_SENT, bandera SAMPLE.
- `tests/test_import.py` — columna faltante (error específico), fila inválida omitida con motivo, mezcla sample/producción, hoja obligatoria, históricos (B/C, lb→kg, no-material).
- `tests/test_overrides_api.py` — override conserva original; slice vertical API (proyecto → MCJ → Cost Master → cálculo → explain → override → recálculo → versión 1 intacta → audit log).
- `tests/golden/<caso>/` — input, expected_interpretation (fase 4+), validated_interpretation, expected_cost_result.

Cada proyecto real calibrado debe agregar un golden case.

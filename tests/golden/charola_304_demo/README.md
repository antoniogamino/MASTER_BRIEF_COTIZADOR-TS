# Golden case: charola_304_demo (SAMPLE)

- `input.json` — entrada (captura manual, demo 1).
- `expected_interpretation.json` — pendiente: se llena cuando exista el intérprete de texto/dibujo (fase 4-5).
- `validated_interpretation.json` — MCJ validado por humano (aquí = input).
- `expected_cost_result.json` — números esperados con `rules/default_rules_v1.yaml` + `COST_MASTER_SAMPLE.xlsx` @ 2026-10-06.

Validación manual de la línea de material C1:
700 × 500 × 1.5 mm × 1e-9 × 7930 kg/m³ = 4.1633 kg neto → ×1.05 = 4.3714 consumido → /0.75 = 5.8286 comprado
× 92.50 MXN/kg (nivel A, COT-EJ-1001) = 539.14 MXN.

Al calibrar con proyectos reales de T&S, cada caso real tendrá su carpeta con estos mismos archivos.

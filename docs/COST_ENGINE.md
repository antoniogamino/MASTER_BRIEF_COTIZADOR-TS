# Cost Engine

`calculate(job, master, rules, as_of) -> CostResult` — determinístico, sin IA, sin reloj, no muta la entrada.

## Contrato de una línea de costo

Cada `CostLine` responde *"¿de dónde salió este número?"*:

```
L0008  C1/J-ESQ: soldadura GTAW corner  [complete]
Fórmula: hours = length_m × side_mult / productivity × Π(factors) → cost = setup_hr × rate + run_hr × multiplier × rate
  weld_length_m    = 0.4      ← derived: components[1].processes[2].joints[0].weld_length/1000
  side_multiplier  = 2        ← rules@1.0.0-sample#…:welding.side_multiplier[both_sides] ← …side (explicit)
  productivity     = 1.2 m/hr ← rules@…:welding.productivity_m_per_hr[GTAW]
  penetration_f    = 1        ← NOT APPLIED: …penetration unknown
  hourly_rate      = 520 MXN/hr ← cost_master:process_rates[welding]
```
(`tsq explain <costing.json> <line_id>` o `GET /projects/{p}/results/{v}/explain/{line}`)

- `one_time`: setup, programación, NRE, cargos por lote — se amortiza en la cantidad.
- `per_unit`: por unidad de producto cotizado (ya multiplicado por la cantidad del componente en el ensamble).
- Total para cantidad Q: `one_time + per_unit × Q`. Por eso el precio unitario baja con la cantidad **sólo** por amortización de setup (sec. 72), no por descuentos arbitrarios.
- `status = missing` + `missing_reason` → la línea no suma; el resultado es **Partial Cost** y la cobertura lo muestra.

## Modelos por categoría

| Categoría | Fórmula (todas las constantes en el rule set) |
|---|---|
| Material | net = geometría × ρ (lámina/placa: L×W×t; barra: π/4·D²·L; tubo: π/4·(OD²−ID²)·L; perfiles: `net_weight` capturado). consumed = net × (1+scrap%). purchased = consumed / aprovechamiento%. costo = purchased × precio − (purchased−consumed) × precio × crédito_remanente%. Precio: jerarquía A→D, luego más reciente; nivel C × adjustment_factor; FX por política. |
| Láser | setup (una vez) + [carga + manejo + corte/velocidad(espesor)×f_material + perforaciones×t_perforación] por pieza, × tarifa. Cargo mínimo por pedido. |
| Doblez | setup×n_setups + cambio_herramienta×n + [dobleces × t_doblez × f_espesor × f_tamaño × f_manejo + manejo]. |
| Soldadura | por junta: horas = m × lados / productividad × f_material × f_espesor × f_junta × f_acceso × f_sanitario × f_purga × f_penetración × f_continuidad × f_posición × f_pieza_pequeña. Consumibles por metro depositado (argón, aporte, tungsteno, + argón de purga). |
| Pulido superficial | horas = área × lados / tasa(acabado final) × f_geometría × f_acceso; + % consumibles. |
| Acabado de soldadura | horas = m × lados / tasa(esmerilado / difuminado / al ras) × f_acceso × f_Ra; + % consumibles. **Modelo distinto del pulido.** |
| Maquinado | setup × f_tolerancia + ciclo × f_tolerancia (por tolerancia real más cerrada); + tooling una vez. |
| Genéricos | setup + (run + handling + inspection) × tarifa del proceso (mapa en reglas). `unknown` ⇒ Missing. |
| Subcontrato | (cotización × cantidad + one_time + logística) × (1 + markup de política). Sin cotización ⇒ Missing. |
| BUY | unit_cost × cantidad en ensamble (+ FX). Sin precio ⇒ **Missing Cost**. |
| Calidad / Empaque / Logística | ítems `required`/`inferred` costeados desde Cost Master; `unknown` ⇒ alerta, no costo; caja de madera por volumen del bounding box + holgura. |
| Ingeniería / NRE / Fixtures | Σ horas × tarifa (una vez); fixture reusable ⇒ amortizado. |

## Del costo al precio (Commercial Engine)

```
Base manufacturing cost        Σ líneas completas (excl. logística)
+ Risk contingency             (RISK_ENGINE.md)
+ Rework contingency
= Adjusted manufacturing cost
+ Manufacturing overhead       ajustado × %
+ Administrative overhead      ajustado × %
+ Commercial costs             logística + (ajustado + overheads) × %
+ Rush premium                 ajustado × %[normal/urgent/expedite]
= Total internal cost
Suggested sell price = Total internal cost / (1 − margen)       ← margen real
Markup informativo   = precio / costo − 1                        ← sólo informativo
Rounded price        = redondeo(precio_unitario, step) × Q
Approved price       = humano
```

**Stop conditions** (recomendación `BLOCKED` salvo `proceed_with_assumptions` + aprobador): costo crítico faltante, cantidad desconocida, moneda desconocida, conflicto de material, páginas faltantes.
**Approval gates** (configurables): CEI < 70 ⇒ ingeniería; riesgo HIGH/VERY_HIGH ⇒ gerencia.

## Garantías verificadas por tests

Determinismo bit a bit · no mutación de la entrada · unidades (pulgadas = mm) · jerarquía de precio (A sobre D más barato) · no se asume 304 / #4 / lado de soldadura · Partial Cost · roll-up de ensamble · FX trazable · margen ≠ markup · contingencia independiente del margen · trazabilidad de toda línea completa.

# Importación de datos

## COST_MASTER.xlsx
Hojas obligatorias: **Materials, Processes**. Opcionales: Machines (= Processes), Labor, Consumables, Packaging, Quality, Logistics, FX, RiskParameters. Plantilla: `data/sample/COST_MASTER_SAMPLE.xlsx` (`python scripts/make_sample_data.py`).

| Hoja | Columnas obligatorias | Opcionales |
|---|---|---|
| Materials | price_id, grade, form, price_per_kg, currency, price_date, source_level (A–D), source_type | thickness_min_mm, thickness_max_mm, supplier, reference, adjustment_factor, is_sample |
| Processes / Machines | rate_key, hourly_rate, currency | description, rate_type, minimum_charge, effective_date, estimated, is_sample |
| Labor | labor_key, salary_cost, productive_hours_per_month, currency | benefits, burden, indirect, is_sample |
| Consumables / Packaging / Quality / Logistics | item_key, unit, unit_cost, currency | description, price_date, supplier, is_sample |
| FX | base, quote, reference_fx, current_fx, protected_fx, fx_date, fx_source | is_sample |
| RiskParameters | factor_key, weight | |

Validación: columnas faltantes (error con nombres esperados y encontrados), tipos, monedas (MXN/USD/EUR), fechas, formas de material, niveles, duplicados (advertencia, se conservan), outliers (>2× / <0.5× mediana → `possible_outlier`, nunca se eliminan), alias de grado (raw conservado). **Mezclar filas sample y producción = error fatal.** Reporte: imported / skipped / warnings / errors por hoja (`tsq import-master archivo.xlsx`).

`rate_key` que usa el motor por defecto: laser_cutting, bending, rolling, welding, surface_polishing, weld_finishing, cnc_lathe, cnc_mill, manual_lathe, manual_mill, drill_press, passivation, electropolishing, inspection, general_labor, saw_cutting, plasma_cutting, waterjet, engineering. Consumibles: argon (L), filler_rod (kg), tungsten (ea). Empaque: cardboard_box, wood_crate_m3, pallet, plastic_bag, desiccant, foam, nimf15, surface_protection.

## HISTORICAL_PURCHASES.xlsx
Columnas: purchase_id, date, supplier, supplier_part_number, description, material_grade, material_form, dimensions, quantity, unit, currency, unit_price, total_price, purchase_order, project, notes (+ thickness_mm, adjustment_factor, is_sample). Compras sin grado o con unidad no convertible a kg se omiten con advertencia (no se adivina el peso). Nivel **B** si la compra es ≤ 90 días (configurable), si no **C** con `adjustment_factor`. `merge_prices()` crea un Cost Master **nuevo** (versión nueva); el anterior queda intacto.

## Actualización de precios
MVP: `adjustment_factor` manual (histórico × factor). Se muestran precio original, fecha, factor y precio ajustado en la traza. Proveedores de inflación/índices/FX: interfaces en `providers/base.py`.

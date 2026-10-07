# Reglas

Archivo: `rules/default_rules_v1.yaml` (`rule_set_version: 1.0.0-sample`, **valores de ejemplo**). Identidad = versión + hash SHA-256 del contenido (`rules@1.0.0-sample#355f…`), guardada en cada resultado.

Política de cambios:
1. Nunca editar un rule set usado en cotizaciones de producción: copiar a `default_rules_v2.yaml`, cambiar `rule_set_version`, apuntar `TSQ_RULES_PATH`.
2. Correr `python scripts/regression.py` para ver cuánto cambian los golden cases; revisar y sólo entonces `--update`.
3. Tablas por banda usan **límite superior inclusivo** (`max_thickness`, `max_dim`, `max_ra`); tolerancias usan límite inferior exclusivo (`min_tol`).

Secciones: `money` (política FX, moneda de costeo) · `price_recency_days` · `material` (densidades, defaults de scrap/aprovechamiento, alias) · `laser` · `bending` · `rolling` · `welding` · `polishing` · `weld_finishing` · `machining` · `generic_process_rate_keys` · `outsourcing` · `packaging` · `engineering` · `minimum_charges` · `risk` · `cei` · `commercial` (overheads, margen default, redondeo, prima rush, stop conditions, approval gates).

Futuro (sec. 132–133): rule sets por familia de producto / cliente / material / acabado vía `RuleSet.with_overrides()`, siempre visibles como defaults del perfil de cliente — nunca lógica "IKA" en el código general.

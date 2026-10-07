# Intérpretes (fases 4–6)

Contrato en `backend/ts_quoter/interpreters/base.py`. Los tres (texto, dibujo, híbrido) implementan `ManufacturingInterpreter.build_requests()` y producen el **mismo** MCJ.

Flujo: `RAW → FACT EXTRACTION → TECHNICAL INTERPRETATION → MANUFACTURING INFERENCE → JSON → Pydantic → (1 reparación controlada) → valid | partial | failed_interpretation`.

Reglas para los prompts (`/prompts/<interprete>/<versión>.md`):
- Distinguir lo **dicho** (`explicit` + `source_reference` con página/región/extracto) de lo **inferido** (`inferred` + confianza).
- Nunca completar dimensiones, material (no asumir 304), acabado (no asumir #4), lados de soldadura o precios. Usar `unknown`.
- Contradicciones entre fuentes → `conflicts[]`, nunca reemplazo silencioso. Dibujo y texto tienen igual jerarquía inicial.
- La IA **no** produce costos; a lo sumo magnitudes técnicas (p.ej. longitud de soldadura estimada) marcadas como inferidas.
- Generar preguntas técnicas concretas sólo cuando cambian costo, fabricabilidad, calidad o entrega.

Fallas contempladas (sec. 83): API caída/timeout (`AIProviderError`), JSON inválido, respuesta parcial, campos alucinados (rechazados por `extra=forbid`), violación de esquema, componentes duplicados (rechazados), unidades incorrectas (rechazadas por `units.py`), PDF escaneado/rotado/cifrado/multi-dibujo (fase 5). En todos: el proyecto y la última interpretación válida se conservan; el usuario puede reintentar o capturar manualmente.

Trazabilidad IA: `model`, `prompt_version`, `input_hash`, `output_hash`, archivos enviados (`sent_to_ai`). Nombres de modelo sólo en `.env` (`TSQ_AI_TEXT_MODEL`, `TSQ_AI_VISION_MODEL`, `TSQ_AI_FALLBACK_MODEL`).

## Estado: Interpreter 1 (texto) implementado

```
tsq text --file rfq.txt --qty 10 --currency MXN --customer "Cliente" \
         --master COST_MASTER.xlsx --as-of 2026-10-06 --out salida/        # IA + costeo en un paso
tsq text "Charola AISI 304 de 500 x 300 x 100 ..." --qty 10 --currency MXN  # sólo interpretación
tsq text --file rfq.txt --replay salida_ia.json ...                         # reprocesar una salida guardada (sin API)
```
API: `POST /projects/{p}/interpret/text {text, quantity, currency, customer, export, user}` → nueva versión de interpretación (`interpreter=text`).

Configuración (`.env`): `TSQ_AI_PROVIDER=anthropic`, `TSQ_AI_API_KEY`, `TSQ_AI_TEXT_MODEL` (+ `TSQ_AI_FALLBACK_MODEL` opcional).

Piezas:
- `prompts/text/v1.md` — instrucciones versionadas (reglas de hecho/inferencia, calibres inox, desarrollo de charolas, separación pulido vs acabado de soldadura).
- `interpreters/payload.py` — lo que la IA devuelve (`InterpretationPayload`) y `merge()` con lo capturado por el humano: lo humano manda; si el texto dice otra cosa (p.ej. 20 piezas vs 10 capturadas) se crea `Conflict`.
- `interpreters/guards.py` — guardas determinísticas, independientes del modelo:
  1. `explicit` exige cita literal que exista en el texto; si no, se degrada a `inferred` (conf ≤ 0.5).
  2. Si el dato sin cita es **crítico** (lados de soldadura/pulido, grado, acabado final, espesor, cantidad) queda `unknown`.
  3. La IA no puede producir `user_confirmed` ni `defaulted`.
  4. Montos no explícitos se eliminan (Regla 1). Confianza de inferencias topada en 0.85.
- `providers/anthropic.py` — Messages API con `tool_choice` forzado (JSON estructurado), reintentos 429/5xx, fallback de modelo, log en `logs/ai.log` (modelo, prompt, hashes, uso; nunca la API key).

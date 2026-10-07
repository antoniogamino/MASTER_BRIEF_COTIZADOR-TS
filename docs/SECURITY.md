# Seguridad de datos

- Aplicación **local**; la API escucha en `127.0.0.1` por defecto. No exponer a Internet.
- Archivos del cliente: copia original inmutable (sólo lectura) con SHA-256; nunca se modifican.
- Sólo se envían a la IA los archivos que el usuario dispara en una interpretación; quedan marcados `sent_to_ai` y listados en `InterpretationRun.files_sent_to_ai`.
- Secretos sólo en `.env` (fuera de git). `TSQ_AI_API_KEY` se lee al momento de usarla; nunca se registra en logs ni se serializa.
- Logs separados (app / ai / calc / error) sin contenido de API keys.
- Roles MVP: admin, estimator, reviewer (campo `users.role`); sin sistema de permisos complejo todavía.
- Costos internos nunca salen en documentos para cliente: el Excel exportado es "Internal Costing Report".
- Backups: ver README (`scripts/backup.sh`).

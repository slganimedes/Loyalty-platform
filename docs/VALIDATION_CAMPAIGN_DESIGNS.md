# Validación de campañas, diseños y modo público — 2026-09-22

Implementación y decisiones: [CAMPAIGN_DESIGNS.md](CAMPAIGN_DESIGNS.md).
Ejemplo completo generado por el servicio real: [points-pass.json](examples/points-pass.json).

## Resultados ejecutados

| Directorio | Comando / comprobación | Resultado |
| --- | --- | --- |
| `api` | `python -m pytest -q` | **92 passed**, última ejecución 29,03 s. Incluye regresiones, migración, modo público/protegido, los doce meses y seed sin contraseña en modo público. |
| `api` | `python -m ruff check app tests seed.py` | Sin errores. |
| `api` | `python -m ruff format --check app tests seed.py` | 34 archivos formateados correctamente. |
| Raíz | `python -m ruff check --select E4,E7,E9,F,I scripts/check_deployment.py scripts/render_install_compose.py scripts/export_points_example.py` | Sin errores. |
| Raíz | `python -m ruff format --check scripts/check_deployment.py scripts/render_install_compose.py scripts/export_points_example.py` | 3 archivos correctos. |
| `admin-web` | `npm run build` | Vite: 104 módulos; compilación terminada correctamente. |
| `admin-web` | `npm run test:e2e` | **5 passed**, 28,0 s. API y navegador reales con DB temporal y autenticación activada; se omite la prueba exclusiva del modo público, ejecutada por separado. |
| `admin-web` | `BROWSER_AUTH_ENABLED=false` y `npx playwright test tests/public-mode.spec.js` | **1 passed**. Entrada sin login, alta con fecha, imágenes, textos, preview y persistencia tras recargar. En PowerShell: `$env:BROWSER_AUTH_ENABLED='false'` antes del comando. |
| Raíz | `python scripts/export_points_example.py` | JSON generado; pytest compara su contenido con el resultado del builder. |
| Raíz | `python scripts/render_install_compose.py --unraid-ref 38bcca181f12ec258f885e31961604386f6f7532` | Plantillas regeneradas con la configuración nueva; Unraid fija este commit de código. |
| Raíz | `docker compose config -q` | Compose local válido. |
| Raíz | `docker compose -f docker-compose.unraid.yml config -q` | Sintaxis/estructura Unraid válidas; no arranca el túnel ni valida credenciales. |
| Raíz | `docker compose -f docker-compose.install.yml config -q` | Plantilla install válida. |
| Raíz | `docker compose build api admin-web` | Ambas imágenes construidas correctamente; dependencias Python/Pillow y build Node verificados en Linux. |
| Raíz | `python scripts/check_deployment.py --inline` | Arranque desde archivo de fuentes, instalación de dependencias, build web, healthchecks, rutas SPA/docs, modo público sin token, subida/publicación de imágenes, creación de diseño, inscripción y pago. Reinicio de API y verificación de imágenes, diseño y puntos persistentes: correcto. |
| `api` | Inspección de `/openapi.json` en pytest | Esquemas `PassDesignOut`/`EnrollmentOut`; sin seguridad en modo público, Bearer restablecido en modo protegido. |
| Raíz | `git diff --check` | Código de salida 0 con configuración normal del repositorio. |

Las migraciones se ejecutaron sobre bases temporales nuevas y un esquema anterior reconstruido con clientes, campañas, imágenes, movimientos y pases. Se comprobó `PRAGMA foreign_key_check`, idempotencia y el snapshot anterior con `integrity_check`. El seed se ejecutó dos veces en cada modo (público/protegido), en DB temporales: conserva dos comercios, dos diseños completos, dos inscripciones y ningún pase emitido. El modo público no crea una cuenta de administrador ni requiere contraseña.

Los fallos encontrados durante el desarrollo se corrigieron antes de la última ejecución: ajustes de fixtures a la inscripción explícita, expectativas de reutilización del GenericObject y de respuesta 404 para comercios eliminados, comparación del identificador externo desde persistencia, reconstrucción del esquema viejo en la prueba y formato/importaciones. Una comprobación con `core.autocrlf=false` produjo falsos avisos sobre finales CRLF en Windows; el control final usa la configuración normal y pasa.

## Cobertura de los criterios solicitados

| Criterios | Pruebas principales |
| --- | --- |
| 1–6: propiedad, varias campañas, cero clientes, N:M, duplicados, otro comercio | `test_many_campaigns_empty_explicit_membership_and_pending_customer`, `test_cross_merchant_batch_and_customer_creation_roll_back`. Incluyen unicidad, rollback de lotes y trigger SQLite de pertenencia. |
| 7: puntos por campaña | `test_points_only_accrue_in_active_enrollments_and_history_survives_archive`; regresiones del motor de puntos/sellos y pagos idempotentes. |
| 8 y 12: diseño único, borrador, color | `test_design_singleton_draft_color_and_atomic_publication`. |
| 9–11: uploads privados, autorización, contenido y límites | `test_upload_validates_content_and_normalizes_public_images` (PNG/JPEG/WebP), `test_upload_rejects_invalid_content`, `test_upload_size_pixels_and_authorization`. |
| 13–16: payload, datos reales, ausencia de marca fija, QR e idempotencia | `test_points_contract_is_deterministic_tenant_scoped_and_opaque`, `test_generic_provider_contract_updates_and_revokes_with_stable_object`, `test_documented_example_matches_production_builder`. JWT firmado y transporte Google simulado. |
| 17: aislamiento | Con `AUTH_ENABLED=true`: `test_tenant_resource_access_and_foreign_assets`, pruebas previas de roles, borrado y pases; pagos sin sesión/otro comercio rechazados. En modo público se desactiva deliberadamente el control de acceso, conservando la integridad de las relaciones. |
| 18: fallos parciales | `test_failed_commit_never_publishes_assets_or_leaves_campaign`, prueba de fallo de segunda subida y lote inválido, `test_invalid_public_base_rejects_upload_without_persistence`. |
| 19: interfaz | `designer.spec.js`: preview, muestras, validación, errores de subida, carga, persistencia, edición, selección, inscripción previa, suspensión y móvil sin desbordamiento horizontal. |
| 20: regresiones y migración | Suite completa; `test_migration_preserves_balances_membership_images_passes_and_is_idempotent`, `test_seed_creates_complete_designs_enrollments_and_is_repeatable`. |

`test_public_mode.py` comprueba el acceso anónimo administrativo, pagos, uploads, Swagger y callbacks/descargas Apple, los textos del diseño y la fecha persistida del cliente. Se verifica que volver a activar autenticación restaura los rechazos sin token. Las capturas de escritorio y móvil se revisaron visualmente y se generan en `admin-web/test-results/campaign-designer-{desktop,mobile}.png` (directorio ignorado por Git).

## Límites de esta validación

- No hay un comando de type checking configurado en el repositorio (frontend JavaScript, sin TypeScript/mypy/pyright). Se ejecutaron Ruff, compilación Vite y pruebas; no se presenta eso como una comprobación estática de tipos.
- Google/Apple se prueban con transporte simulado, certificados de prueba y JWT/firma reales de fixtures. No se emitieron tarjetas en las cuentas reales ni se probó su instalación en un teléfono. La aceptación del issuer, permisos de la cuenta de servicio y entrega APNs requieren la instalación real configurada.
- La publicación HTTPS se construye y valida desde `PUBLIC_API_URL`. La prueba Docker recupera imágenes por el proxy HTTP interno; no instala un túnel Cloudflare ni un certificado TLS público de prueba. El dominio real debe apuntar a la API y dejar pública la ruta de imágenes.
- No se ha desplegado sobre el Unraid real ni migrado su DB. La publicación del código y la referencia fijada de la plantilla permiten ejecutar el procedimiento documentado en [REDEPLOY_UNRAID.md](REDEPLOY_UNRAID.md); las validaciones locales no sustituyen la comprobación posterior del servidor real.
- Se mantiene la arquitectura piloto de SQLite y un único worker. Para instalaciones grandes, el backfill de relaciones implícitas (clientes × campañas por comercio), los BLOB y la sincronización de muchos pases deben dimensionarse; la capa de almacenamiento permite una futura implementación externa.
- El rollback por snapshot debe hacerse antes de reabrir escrituras o con reconciliación de actividad posterior. No revierte efectos ya notificados a Google/Apple.

La lista de ficheros, relaciones, endpoints, variables nuevas, estrategia de almacenamiento, mapeo del pase, migración y rollback está en [la guía técnica](CAMPAIGN_DESIGNS.md).

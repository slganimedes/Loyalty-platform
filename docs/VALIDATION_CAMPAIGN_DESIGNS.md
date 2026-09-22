# Validación de campañas, API abierta y panel con contraseña — 2026-09-22

Implementación y decisiones: [CAMPAIGN_DESIGNS.md](CAMPAIGN_DESIGNS.md).
Ejemplo completo generado por el servicio real: [points-pass.json](examples/points-pass.json).

## Resultados ejecutados

### Reanudación del 22 de septiembre de 2026

Se ha vuelto a validar el árbol de trabajo con la separación entre login obligatorio
y API abierta: **93 pruebas de backend correctas** (31,04 s), Ruff sin errores y
34 archivos con formato correcto, compilación Vite correcta, **5 pruebas de navegador
correctas** en modo protegido (25,1 s; la prueba de modo abierto se omite aquí) y
**1 prueba de navegador correcta** en modo abierto (9,4 s). Tanto `git diff --check`
como `git diff --cached --check` terminaron correctamente.

En el primer intento Docker seguía bloqueado: una consulta `docker version` agotó
25 segundos y otra devolvió HTTP 500. En la siguiente reanudación el motor ya
respondía y se completaron las comprobaciones pendientes:

- `python scripts/check_deployment.py` (antes: modo inline) terminó correctamente: instalación,
  compilación, healthchecks, login y logout reales, perfil protegido, API de negocio
  abierta, imágenes, diseño, inscripción, pago y persistencia tras reiniciar la API.
  Los recursos temporales del proyecto de pruebas se retiraron al terminar.
- `docker compose build api admin-web` y
  `docker compose up -d --force-recreate --wait --wait-timeout 180 api admin-web`
  terminaron correctamente. Ambos servicios locales están **healthy**.
- Antes del arranque se creó un snapshot SQLite consistente en
  `data/backups/before-local-resume-20260922T211510Z-e61a1713.db`, con
  `PRAGMA integrity_check` correcto.
- Panel local: `http://localhost:8080`; API: `http://localhost:8000/docs`.
  Se verificaron HTTP 200 para panel, health, docs, OpenAPI y ruta de campañas;
  perfil anónimo y contraseña incorrecta devuelven 401. La API de negocio anónima
  responde 200 y OpenAPI refleja la separación de autenticación.

La contraseña bootstrap del `.env` actual no coincidía con la cuenta local existente:
el login devolvía 401 y la comparación con su hash almacenado confirmó la diferencia.
La variable bootstrap solo crea cuentas nuevas. Con autorización expresa del usuario,
se restableció la contraseña de esa cuenta al valor actual del `.env` y se revocaron
sus cinco sesiones anteriores, en una única transacción. No se imprimieron secretos.
Una comprobación adicional con Chromium contra el panel Docker local verificó login
con esas credenciales, perfil autenticado, sesión tras recargar, logout que revoca el
token y redirección al login al intentar navegar después del cierre de sesión.
Esta validación precede a la publicación de la versión con Compose único.

| Directorio | Comando / comprobación | Resultado |
| --- | --- | --- |
| `api` | `python -m pytest -q` | **93 passed**, última ejecución 31,04 s. Incluye regresiones, migración, API abierta/protegida, login obligatorio, roles con token en modo abierto, los doce meses y seed con administrador en ambos modos. |
| `api` | `python -m ruff check app tests seed.py` | Sin errores. |
| `api` | `python -m ruff format --check app tests seed.py` | 34 archivos formateados correctamente. |
| Raíz | `python -m ruff check --select E4,E7,E9,F,I scripts/check_deployment.py scripts/export_points_example.py` | Sin errores. |
| Raíz | `python -m ruff format --check scripts/check_deployment.py scripts/export_points_example.py` | 2 archivos correctos tras eliminar el generador. |
| `admin-web` | `npm run build` | Vite: 104 módulos; compilación terminada correctamente. |
| `admin-web` | `npm run test:e2e` | **5 passed**, 25,1 s. API y navegador reales con DB temporal y autenticación activada; se omite la prueba exclusiva de API abierta, ejecutada por separado. |
| `admin-web` | `BROWSER_AUTH_ENABLED=false` y `npx playwright test tests/public-mode.spec.js` | **1 passed**, 9,4 s. API anónima, rechazo de contraseña incorrecta, login real, alta con fecha, imágenes, textos, preview, persistencia tras recargar y logout que bloquea la navegación. En PowerShell: `$env:BROWSER_AUTH_ENABLED='false'` antes del comando. |
| Raíz | `python scripts/export_points_example.py` | JSON generado; pytest compara su contenido con el resultado del builder. |
| Raíz | `docker compose config -q` | Compose local válido. |
| Raíz | `docker compose -f docker-compose.unraid.yml config -q` | Sintaxis/estructura Unraid válidas; no arranca el túnel ni valida credenciales. |
| Raíz | `docker compose build api admin-web` | Ambas imágenes construidas correctamente; dependencias Python/Pillow y build Node verificados en Linux. |
| Raíz | `python scripts/check_deployment.py` (antes: modo inline) | Correcto tras recuperar Docker: instalación, compilación, healthchecks, sesiones reales, negocio sin token, imágenes, diseño, inscripción, pago y persistencia tras reiniciar la API. |
| Raíz | `docker compose up -d --force-recreate --wait --wait-timeout 180 api admin-web` | Correcto: API y admin-web healthy, con backup SQLite previo verificado. |
| `api` | Inspección de `/openapi.json` en pytest | Esquemas `PassDesignOut`/`EnrollmentOut`; perfil/logout con seguridad en ambos modos; operaciones de negocio abiertas o protegidas según configuración. |
| Raíz | `git diff --check` | Código de salida 0 con configuración normal del repositorio. |

Las migraciones se ejecutaron sobre bases temporales nuevas y un esquema anterior reconstruido con clientes, campañas, imágenes, movimientos y pases. Se comprobó `PRAGMA foreign_key_check`, idempotencia y el snapshot anterior con `integrity_check`. El seed se ejecutó dos veces en cada modo (API abierta/protegida), en DB temporales: conserva dos comercios, dos diseños completos, dos inscripciones y ningún pase emitido. Ambos modos crean un administrador con contraseña cuando aún no existe.

Los fallos encontrados durante el desarrollo se corrigieron antes de la última ejecución: ajustes de fixtures a la inscripción explícita, expectativas de reutilización del GenericObject y de respuesta 404 para comercios eliminados, comparación del identificador externo desde persistencia, reconstrucción del esquema viejo en la prueba y formato/importaciones. Una comprobación con `core.autocrlf=false` produjo falsos avisos sobre finales CRLF en Windows; el control final usa la configuración normal y pasa.

## Cobertura de los criterios solicitados

| Criterios | Pruebas principales |
| --- | --- |
| 1–6: propiedad, varias campañas, cero clientes, N:M, duplicados, otro comercio | `test_many_campaigns_empty_explicit_membership_and_pending_customer`, `test_cross_merchant_batch_and_customer_creation_roll_back`. Incluyen unicidad, rollback de lotes y trigger SQLite de pertenencia. |
| 7: puntos por campaña | `test_points_only_accrue_in_active_enrollments_and_history_survives_archive`; regresiones del motor de puntos/sellos y pagos idempotentes. |
| 8 y 12: diseño único, borrador, color | `test_design_singleton_draft_color_and_atomic_publication`. |
| 9–11: uploads privados, autorización, contenido y límites | `test_upload_validates_content_and_normalizes_public_images` (PNG/JPEG/WebP), `test_upload_rejects_invalid_content`, `test_upload_size_pixels_and_authorization`. |
| 13–16: payload, datos reales, ausencia de marca fija, QR e idempotencia | `test_points_contract_is_deterministic_tenant_scoped_and_opaque`, `test_generic_provider_contract_updates_and_revokes_with_stable_object`, `test_documented_example_matches_production_builder`. JWT firmado y transporte Google simulado. |
| 17: aislamiento | Con `AUTH_ENABLED=true`: `test_tenant_resource_access_and_foreign_assets`, pruebas previas de roles, borrado y pases. Las sesiones aportadas conservan los permisos del comercio en ambos modos. En API abierta, las llamadas sin token se permiten deliberadamente, conservando la integridad de las relaciones. |
| 18: fallos parciales | `test_failed_commit_never_publishes_assets_or_leaves_campaign`, prueba de fallo de segunda subida y lote inválido, `test_invalid_public_base_rejects_upload_without_persistence`. |
| 19: interfaz | `designer.spec.js`: preview, muestras, validación, errores de subida, carga, persistencia, edición, selección, inscripción previa, suspensión y móvil sin desbordamiento horizontal. |
| 20: regresiones y migración | Suite completa; `test_migration_preserves_balances_membership_images_passes_and_is_idempotent`, `test_seed_creates_complete_designs_enrollments_and_is_repeatable`. |

`test_public_mode.py` comprueba llamadas anónimas de negocio, pagos, uploads, Swagger y callbacks/descargas Apple, los textos del diseño y la fecha persistida del cliente. Verifica que login siempre exige credenciales y perfil/logout siempre exigen sesión, que una sesión revocada no se convierte en anónima y que se mantienen los permisos de usuarios SME autenticados. Las capturas de escritorio y móvil se revisaron visualmente y se generan en `admin-web/test-results/campaign-designer-{desktop,mobile}.png` (directorio ignorado por Git).

## Límites de esta validación

- No hay un comando de type checking configurado en el repositorio (frontend JavaScript, sin TypeScript/mypy/pyright). Se ejecutaron Ruff, compilación Vite y pruebas; no se presenta eso como una comprobación estática de tipos.
- Google/Apple se prueban con transporte simulado, certificados de prueba y JWT/firma reales de fixtures. No se emitieron tarjetas en las cuentas reales ni se probó su instalación en un teléfono. La aceptación del issuer, permisos de la cuenta de servicio y entrega APNs requieren la instalación real configurada.
- La publicación HTTPS se construye y valida desde `PUBLIC_API_URL`. La prueba Docker recupera imágenes por el proxy HTTP interno; no instala un túnel Cloudflare ni un certificado TLS público de prueba. El dominio real debe apuntar a la API y dejar pública la ruta de imágenes.
- No se ha desplegado sobre el Unraid real ni migrado su DB. La publicación del código y la referencia fijada de la plantilla permiten ejecutar el procedimiento documentado en [REDEPLOY_UNRAID.md](REDEPLOY_UNRAID.md); las validaciones locales no sustituyen la comprobación posterior del servidor real.
- La última corrección de login/API se verificó con pytest, navegador, Ruff, build Docker, Compose aislado y recreación local. El login completo pasa tanto con credenciales sintéticas en el entorno aislado como en el panel Docker local tras el restablecimiento autorizado de la cuenta al valor del `.env`.
- Se mantiene la arquitectura piloto de SQLite y un único worker. Para instalaciones grandes, el backfill de relaciones implícitas (clientes × campañas por comercio), los BLOB y la sincronización de muchos pases deben dimensionarse; la capa de almacenamiento permite una futura implementación externa.
- El rollback por snapshot debe hacerse antes de reabrir escrituras o con reconciliación de actividad posterior. No revierte efectos ya notificados a Google/Apple.

La lista de ficheros, relaciones, endpoints, variables nuevas, estrategia de almacenamiento, mapeo del pase, migración y rollback está en [la guía técnica](CAMPAIGN_DESIGNS.md).

## Compose único para Unraid y local — 2026-09-22

Se conserva solo `docker-compose.unraid.yml`. Los tres Compose alternativos y su
generador se han eliminado. El archivo admite ajustes en `x-installation` y
sobrescritura local mediante `.env`; Cloudflare arranca por defecto sin perfiles.
Las rutas Unraid siguen en appdata, y las variables locales seleccionan `./data`
y puertos 8000/8080. Todos los puertos publicados se enlazan a loopback.

`python scripts/check_deployment.py` pasó usando el archivo único y fuentes del
árbol de trabajo, datos sintéticos y recursos aislados. Verificó login obligatorio,
perfil protegido, API de negocio abierta, imágenes, campaña, inscripción, pago y
persistencia tras reiniciar. La configuración comprueba que Cloudflare no tenga
perfil y espere a API/panel saludables. No se conectó un túnel real.

El modo `--published` permite repetir esa prueba descargando el SHA fijado desde
GitHub. La aceptación en Unraid debe comprobar la referencia en los logs de source,
las conexiones de cloudflared y los dos dominios públicos desde datos móviles.

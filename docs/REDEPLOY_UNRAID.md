# Redesplegar en Unraid conservando los datos

Esta versión incorpora **Notificaciones** para campañas o pases individuales, historial de envíos, plantillas y avisos opcionales al registrar pagos. Conserva el diseñador de campañas y las inscripciones existentes. **La web de administración siempre exige usuario y contraseña.** Con `AUTH_ENABLED=false` la API de negocio permite llamadas anónimas, incluidos envíos y borrados; el login del panel no protege esas llamadas directas. Con `true` también se exige autenticación en la API de negocio.

## Cambios respecto a la versión anterior (`b795b88005facab100a69bff759fc8e0b2842bc6`)

El archivo que se edita en Unraid es **Compose File**, correspondiente a
`docker-compose.unraid.yml`. El cambio mínimo obligatorio es actualizar `SOURCE_REF`
al SHA de la plantilla publicada. Si se mantienen los límites predeterminados,
el Compose anterior funciona cambiando únicamente esa referencia.

La plantilla completa añade estos ajustes en `x-installation` y los pasa a
`services.api.environment`. Son opcionales para personalizar los límites:

| Variable nueva | Valor predeterminado | Función |
| --- | --- | --- |
| `NOTIFICATION_MASS_THRESHOLD` | `100` | Confirmación adicional por encima de 100 titulares. |
| `NOTIFICATION_MAX_PASSES` | `5000` | Máximo de pases en un envío por campaña. |
| `NOTIFICATION_SENDS_PER_HOUR` | `30` | Máximo de solicitudes por comercio y hora. |
| `NOTIFICATION_PASSES_PER_HOUR` | `10000` | Máximo de pases afectados por comercio y hora. |
| `NOTIFICATION_PASSES_PER_DAY` | `3` | Límite por pase en 24 horas; admite valores de 1 a 3. |

Conservar los montajes, puertos, dominios, secreto PAN, credenciales y token de
Cloudflare de la instalación. No hay imágenes, servicios, volúmenes ni dependencias
adicionales. La cola se guarda en SQLite y la procesa la API existente.

La migración `20260925_notifications` crea automáticamente tres tablas de
notificaciones. Los saldos, clientes, campañas y pases existentes se conservan.
En una base con datos se crea un backup en
`/data/backups/before-20260925_notifications-*.db`. Detener el stack y hacer además
la copia completa indicada a continuación. Detalles funcionales y del proveedor:
[NOTIFICATIONS.md](NOTIFICATIONS.md).

## 1. Guardar la configuración y hacer un backup

En el stack existente, guardar una copia privada de **Compose File** con sus valores actuales. Detener el stack desde Compose Manager y copiar el directorio `/mnt/user/appdata/loyalty-platform/data` a una ubicación de backup. Con los procesos parados, la copia incluye coherentemente `loyalty.db`, imágenes y certificados. Si se personalizó `DATA_MOUNT`, copiar esa ubicación real. No borrar el stack ni sus volúmenes.

La API también crea un backup SQLite antes de migrar una base antigua con comercios, pero no sustituye esta copia del despliegue y sus certificados. Ver [migración y rollback](CAMPAIGN_DESIGNS.md#migración-despliegue-y-rollback).

## 2. Sustituir Compose File

Abrir la [plantilla Unraid actual](https://github.com/slganimedes/Loyalty-platform/blob/main/docker-compose.unraid.yml) o su [contenido Raw](https://raw.githubusercontent.com/slganimedes/Loyalty-platform/main/docker-compose.unraid.yml). En **Edit Stack → Compose File**, sustituir el contenido completo por esa plantilla. Es el único Compose, también utilizado en local. El `SOURCE_REF` nuevo ya viene fijado al commit de código de esta entrega; Cloudflare arranca automáticamente sin perfiles.

El `SOURCE_REF` debe ser el de la plantilla actualizada con Notificaciones. Si **Env File** define `SOURCE_REF`, actualizarlo también o eliminar esa línea para usar el valor de Compose File. La versión muy antigua `38bcca1` abría también el panel y no debe reutilizarse para un despliegue con login administrativo.

Reponer los valores privados dentro de `x-installation`:

| Campo | Qué conservar o configurar |
| --- | --- |
| `SOURCE_REF` | Dejar el SHA nuevo de la plantilla, no copiar el antiguo. |
| `AUTH_ENABLED` | `"false"` para probar la API sin token. El panel sigue exigiendo login. |
| `PAN_HASH_SECRET` | **Exactamente el mismo valor de la instalación existente**; cambiarlo impediría reconocer tarjetas previamente vinculadas. |
| `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_PASSWORD` | Conservar los valores privados. Se exige contraseña también con la API abierta; se crea la cuenta solo si aún no existe. Cambiar esta variable no cambia la contraseña de una cuenta ya existente. |
| `PUBLIC_API_URL`, `PUBLIC_ADMIN_URL` | Conservar los dominios públicos HTTPS de API y panel. |
| `GOOGLE_ISSUER_ID` | ID correcto del emisor, entre comillas, sin modificar sus dígitos. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Conservar el token actual del túnel. |
| Configuración `APPLE_*` | Conservar la configuración actual si se utiliza Apple Wallet. |
| `DATA_MOUNT`, `CERTS_MOUNT` | Conservar las rutas existentes. El JSON debe seguir en `data/certs/google-sa.json`, visible en la API como `/certs/google-sa.json`. |
| `PASS_ASSET_MAX_BYTES`, `PASS_ASSET_MAX_PIXELS` | Los valores de plantilla permiten 4 MiB y 16.777.216 píxeles por imagen. |
| `NOTIFICATION_*` | Dejar los cinco valores predeterminados o ajustar los límites de la tabla anterior. |
| `SOURCE_URL`, `GITHUB_TOKEN` | Vacíos para descargar del repositorio público. |

El resto de ajustes puede conservarse. Los valores con un dólar literal deben escribir `$$`, por la interpolación de Compose. No pegar el JSON privado en el YAML ni subir esta copia con credenciales a GitHub.

**ENV FILE** puede permanecer vacío: esta plantilla contiene la configuración en `x-installation`. Si contiene variables antiguas, revisar especialmente `SOURCE_REF`, `DATA_DIR` y `CERTS_DIR`, que prevalecen sobre los valores predeterminados. Para editar un ajuste en Compose File se puede sustituir `${VARIABLE:-valor}` por un valor literal, conservando su ancla `&...`. **UI Labels** y **Stack Settings** pueden conservarse. Mantener el mismo nombre del stack/proyecto para reutilizar sus volúmenes.

## 3. Recrear y esperar al arranque

Con la plantilla guardada, ejecutar **Compose Down** (si no se hizo antes) y **Compose Up** sobre el mismo stack. Down sin la opción de eliminar volúmenes retira contenedores y redes, conservando los datos; no utilizar `down -v` ni marcar la eliminación de volúmenes. Un simple **Restart** no aplica la nueva configuración ni cambia el código fijado por `SOURCE_REF`.

Alternativamente, desde la carpeta real del stack, usando el nombre real de su fichero Compose:

```sh
docker compose -p loyalty -f docker-compose.unraid.yml down
docker compose -p loyalty -f docker-compose.unraid.yml up -d --force-recreate --wait --wait-timeout 600
docker compose -p loyalty -f docker-compose.unraid.yml ps -a
```

Estos comandos asumen que el proyecto se llama `loyalty` y el fichero `docker-compose.unraid.yml`; adaptar ambos si son distintos. Antes de detener los contenedores se pueden consultar las ubicaciones utilizadas por Compose:

```sh
docker inspect loyalty-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}'
docker inspect loyalty-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'
```

El servicio `source` descarga el commit nuevo de GitHub; `web-build` compila el panel. Es normal que ambos terminen como **Exited (0)**. `api` y `admin-web` deben quedar **healthy**, y `cloudflared` en ejecución. No se necesita `--build`: esta plantilla usa imágenes estándar y compila el código mediante sus servicios de preparación. La primera preparación puede tardar varios minutos.

Semántica de las opciones: [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/) y [Docker Compose down](https://docs.docker.com/reference/cli/docker/compose/down/).

## 4. Comprobar la actualización

Los puertos de diagnóstico solo escuchan en loopback (18000/18080 por defecto).
Si están ocupados, cambiar los puertos de host en `x-installation`. Los destinos
de Cloudflare siguen siendo `api:8000` y `admin-web:80`.

Con los dominios configurados en la plantilla:

- Panel: `https://admin.slmartinez.org`. Debe solicitar usuario y contraseña y mostrar el botón de cerrar sesión tras entrar.
- Swagger: `https://api.slmartinez.org/docs`. Con `AUTH_ENABLED=false`, permite ejecutar operaciones de negocio sin credenciales; con `true`, requiere una sesión.
- Sin token, `/api/v1/users/me` debe devolver 401; `/api/v1/merchants` debe responder 200 con la API abierta. Con una sesión válida, `/users/me` devuelve el administrador real y `public_access: false`.
- En Campañas → Nueva campaña aparecen las cuatro secciones, subidas de logo y hero, color, descripciones, etiquetas y preview. Si aparece la interfaz antigua, recargar con `Ctrl+F5` y comprobar el SHA efectivo del stack.
- Al crear un cliente se puede indicar su fecha de alta. El pase usa el mes abreviado y año de esa fecha; por ejemplo, `2023-07-10` produce `jul 2023` en español.
- Las campañas migradas que indiquen revisión de diseño deben abrirse, completar sus imágenes y guardarse. Los pases existentes conservan su familia Google; los nuevos de campañas de puntos completadas usan GenericObject.
- Debe aparecer **Notificaciones** en el menú, con selección de campaña/pase, plantillas, dos vistas previas e historial. En **Pagos**, la casilla **Enviar notificación al cliente** aparece desmarcada.
- Probar primero un pase individual instalado. Revisar el detalle del historial: «Aceptada por Wallet» indica aceptación del proveedor, no confirma que el cliente haya visto el aviso. Los pases Apple antiguos pueden necesitar una actualización previa para incorporar el campo de notificación.

Comprobar que `source` muestra el SHA nuevo y cloudflared registra conexiones. Para comprobar el conector desde la red interna, usar el comando de `/ready` en [COMPOSE_DEPLOYMENT.md](COMPOSE_DEPLOYMENT.md#validación-y-versión-instalada).

Si falla el arranque, revisar `docker logs --tail 100 loyalty-api-1` y los logs de `source`/`web-build` desde Unraid. No publicar credenciales al compartir diagnósticos. Las imágenes se sirven desde `/api/v1/public/pass-assets/{asset_id}`: Cloudflare debe permitir su lectura sin una pantalla de login.

## Rollback

Detener de nuevo el stack, conservar una copia del estado fallido y restaurar el backup anterior con sus archivos coherentes; reponer el Compose privado anterior y su `SOURCE_REF`. Si ya hubo movimientos nuevos, reconciliarlos antes de restaurar: un backup anterior no los contiene. No cambiar el secreto PAN ni eliminar volúmenes. Restaurar SQLite no revierte las notificaciones que Google o Apple ya hayan recibido.

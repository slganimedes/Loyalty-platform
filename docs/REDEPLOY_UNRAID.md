# Redesplegar en Unraid conservando los datos

Esta versión incorpora el diseñador de campañas, inscripciones explícitas, imágenes persistentes, fecha de alta del cliente y acceso sin autenticación. Con `AUTH_ENABLED=false` cualquiera que pueda abrir la URL puede consultar y modificar los datos, incluidos borrados. Para recuperar el acceso con cuentas, configurar `true` y una contraseña de administrador válida.

## 1. Guardar la configuración y hacer un backup

En el stack existente, guardar una copia privada de **Compose File** con sus valores actuales. Detener el stack desde Compose Manager y copiar el directorio `/mnt/user/appdata/loyalty-platform/data` a una ubicación de backup. Con los procesos parados, la copia incluye coherentemente `loyalty.db`, imágenes y certificados. Si se personalizó `DATA_MOUNT`, copiar esa ubicación real. No borrar el stack ni sus volúmenes.

La API también crea un backup SQLite antes de migrar una base antigua con comercios, pero no sustituye esta copia del despliegue y sus certificados. Ver [migración y rollback](CAMPAIGN_DESIGNS.md#migración-despliegue-y-rollback).

## 2. Sustituir Compose File

Abrir la [plantilla Unraid actual](https://github.com/slganimedes/Loyalty-platform/blob/main/docker-compose.unraid.yml) o su [contenido Raw](https://raw.githubusercontent.com/slganimedes/Loyalty-platform/main/docker-compose.unraid.yml). En **Edit Stack → Compose File**, sustituir el contenido completo por esa plantilla. El `SOURCE_REF` nuevo ya viene fijado al commit de código de esta entrega.

Referencia de código de esta entrega: `38bcca181f12ec258f885e31961604386f6f7532`. El commit posterior solo fija esta referencia en la plantilla y documenta el despliegue.

Reponer los valores privados dentro de `x-installation`:

| Campo | Qué conservar o configurar |
| --- | --- |
| `SOURCE_REF` | Dejar el SHA nuevo de la plantilla, no copiar el antiguo. |
| `AUTH_ENABLED` | `"false"` para probar sin login ni tokens. |
| `PAN_HASH_SECRET` | **Exactamente el mismo valor de la instalación existente**; cambiarlo impediría reconocer tarjetas previamente vinculadas. |
| `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_PASSWORD` | Conservar los valores privados. La contraseña se exige al activar autenticación. |
| `PUBLIC_API_URL`, `PUBLIC_ADMIN_URL` | Conservar los dominios públicos HTTPS de API y panel. |
| `GOOGLE_ISSUER_ID` | ID correcto del emisor, entre comillas, sin modificar sus dígitos. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Conservar el token actual del túnel. |
| Configuración `APPLE_*` | Conservar la configuración actual si se utiliza Apple Wallet. |
| `DATA_MOUNT`, `CERTS_MOUNT` | Conservar las rutas existentes. El JSON debe seguir en `data/certs/google-sa.json`, visible en la API como `/certs/google-sa.json`. |
| `PASS_ASSET_MAX_BYTES`, `PASS_ASSET_MAX_PIXELS` | Los valores de plantilla permiten 4 MiB y 16.777.216 píxeles por imagen. |
| `SOURCE_URL`, `GITHUB_TOKEN` | Vacíos para descargar del repositorio público. |

El resto de ajustes puede conservarse. Los valores con un dólar literal deben escribir `$$`, por la interpolación de Compose. No pegar el JSON privado en el YAML ni subir esta copia con credenciales a GitHub.

**ENV FILE** puede permanecer vacío: esta plantilla contiene la configuración en `x-installation`. **UI Labels** y **Stack Settings** pueden conservarse. Mantener el mismo nombre del stack/proyecto para reutilizar sus volúmenes.

## 3. Recrear y esperar al arranque

Con la plantilla guardada, ejecutar **Compose Down** (si no se hizo antes) y **Compose Up** sobre el mismo stack. Down sin la opción de eliminar volúmenes retira contenedores y redes, conservando los datos; no utilizar `down -v` ni marcar la eliminación de volúmenes. Un simple **Restart** no aplica la nueva configuración ni cambia el código fijado por `SOURCE_REF`.

Alternativamente, desde la carpeta real del stack, usando el nombre real de su fichero Compose:

```sh
docker compose -p loyalty -f docker-compose.yml down
docker compose -p loyalty -f docker-compose.yml up -d --force-recreate --wait --wait-timeout 600
docker compose -p loyalty -f docker-compose.yml ps -a
```

Estos comandos asumen que el proyecto se llama `loyalty` y el fichero `docker-compose.yml`; adaptar ambos si son distintos. Antes de detener los contenedores se pueden consultar las ubicaciones utilizadas por Compose:

```sh
docker inspect loyalty-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}'
docker inspect loyalty-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'
```

El servicio `source` descarga el commit nuevo de GitHub; `web-build` compila el panel. Es normal que ambos terminen como **Exited (0)**. `api` y `admin-web` deben quedar **healthy**, y `cloudflared` en ejecución. No se necesita `--build`: esta plantilla usa imágenes estándar y compila el código mediante sus servicios de preparación. La primera preparación puede tardar varios minutos.

Semántica de las opciones: [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/) y [Docker Compose down](https://docs.docker.com/reference/cli/docker/compose/down/).

## 4. Comprobar la actualización

Con los dominios configurados en la plantilla:

- Panel: `https://admin.slmartinez.org`. Debe entrar sin login y mostrar el indicador de modo de prueba público.
- Swagger: `https://api.slmartinez.org/docs`. Debe permitir ejecutar peticiones sin introducir credenciales.
- Estado del acceso: `https://api.slmartinez.org/api/v1/users/me` devuelve `public_access: true`.
- En Campañas → Nueva campaña aparecen las cuatro secciones, subidas de logo y hero, color, descripciones, etiquetas y preview. Si aparece la interfaz antigua, recargar con `Ctrl+F5` y comprobar el SHA efectivo del stack.
- Al crear un cliente se puede indicar su fecha de alta. El pase usa el mes abreviado y año de esa fecha; por ejemplo, `2023-07-10` produce `jul 2023` en español.
- Las campañas migradas que indiquen revisión de diseño deben abrirse, completar sus imágenes y guardarse. Los pases existentes conservan su familia Google; los nuevos de campañas de puntos completadas usan GenericObject.

Si falla el arranque, revisar `docker logs --tail 100 loyalty-api-1` y los logs de `source`/`web-build` desde Unraid. No publicar credenciales al compartir diagnósticos. Las imágenes se sirven desde `/api/v1/public/pass-assets/{asset_id}`: Cloudflare debe permitir su lectura sin una pantalla de login.

## Rollback

Detener de nuevo el stack, conservar una copia del estado fallido y restaurar el backup anterior con sus archivos coherentes; reponer el Compose privado anterior y su `SOURCE_REF`. Si ya hubo movimientos nuevos, reconciliarlos antes de restaurar: un backup anterior no los contiene. No cambiar el secreto PAN ni eliminar volúmenes. Restaurar SQLite no revierte las notificaciones que Google o Apple ya hayan recibido.

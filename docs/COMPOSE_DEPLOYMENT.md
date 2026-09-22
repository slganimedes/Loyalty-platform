# Un único Compose para Unraid y local

El único archivo de arranque es `docker-compose.unraid.yml`. Usa imágenes estándar
de Python, Node, Nginx y Cloudflare, y descarga el código de un commit de GitHub
fijado en `SOURCE_REF`. No requiere clonar el repositorio en Unraid ni construir
imágenes propias. API y panel usan siempre la misma referencia.

Servicios: `source` descarga el código; `web-build` compila el panel; `api` y
`admin-web` ejecutan la aplicación; `cloudflared` conecta el túnel.
**Cloudflare forma parte del arranque normal, sin perfiles opcionales.**
La primera instalación puede tardar varios minutos.

## Unraid: los cuatro botones del editor

1. Abrir **Edit Stack → Compose File** y pegar el archivo completo de esta versión.
2. Editar los valores de `x-installation` en esa copia privada. Se pueden sustituir
   las expresiones `${VARIABLE:-valor}` por valores literales, conservando las anclas
   `&...`. Conservar la nueva referencia de código.
3. **Env File** puede quedar vacío si se rellenan los valores dentro de Compose File.
   Si ya contiene variables, estas prevalecen sobre los valores predeterminados;
   retirar un `SOURCE_REF` antiguo para no desplegar otra versión.
4. Mantener **UI Labels**, **Stack Settings**, el nombre del stack y los directorios
   persistentes de la instalación existente.
5. Ejecutar **Compose Down** sin borrar volúmenes y después **Compose Up**.

Configuración principal:

| Campo | Valor o acción |
| --- | --- |
| `SOURCE_REF` | Conservar el SHA nuevo del archivo publicado. No recuperar el antiguo. |
| `PAN_HASH_SECRET` | Conservar exactamente el secreto de la instalación existente. |
| `BOOTSTRAP_ADMIN_USERNAME/PASSWORD` | Credenciales para crear una cuenta ausente; no restablecen cuentas existentes. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token del túnel de Unraid, necesario para conectar Cloudflare. |
| `DATA_MOUNT` | Conservar el directorio de datos; predeterminado `/mnt/user/appdata/loyalty-platform/data:/data`. |
| `CERTS_MOUNT` | Conservar el directorio de certificados; predeterminado `/mnt/user/appdata/loyalty-platform/data/certs:/certs:ro`. |
| `PUBLIC_API_URL/PUBLIC_ADMIN_URL` | Dominios públicos HTTPS existentes. |
| `AUTH_ENABLED` | `false` abre la API de negocio para pruebas; el panel siempre exige login. |
| `GOOGLE_ISSUER_ID`, `APPLE_*` | Conservar los valores del proveedor. |
| `GITHUB_TOKEN` | Vacío para el repositorio público; token de lectura para un repositorio privado. |
| `SOURCE_URL` | Vacío para descargar el commit desde GitHub. Solo se usa en pruebas de fuentes alternativas. |
| `API_PORT/ADMIN_PORT` | Puertos completos de diagnóstico; por defecto `127.0.0.1:18000:8000` y `127.0.0.1:18080:80`. |

Los puertos publicados se enlazan exclusivamente a loopback; Cloudflare usa la red
interna Docker y no necesita abrir puertos en el router. Si esos puertos están
ocupados en Unraid, modificar los puertos de host en `x-installation`.

Configurar los dos hostnames del túnel:
`api.slmartinez.org → http://api:8000` y
`admin.slmartinez.org → http://admin-web:80`.
El túnel espera a que ambos servicios estén saludables.

## Local con el mismo archivo

Generar el entorno con `python scripts/setup_env.py`. Si el `.env` ya existe,
conservar sus secretos y añadir estas variables:

```dotenv
DATA_DIR=./data
CERTS_DIR=./data/certs
API_PORT=8000
ADMIN_PORT=8080
```

Dejar `SOURCE_REF` sin definir para usar la versión fijada en el Compose. Arrancar:

```sh
docker compose -f docker-compose.unraid.yml config --quiet
docker compose -f docker-compose.unraid.yml up -d --wait --wait-timeout 600 api admin-web
docker compose -f docker-compose.unraid.yml ps -a
```

Panel: http://localhost:8080. API: http://localhost:8000/docs.
Esta selección inicia la aplicación y sus dependencias; no inicia el túnel.
Para probar también Cloudflare en local, configurar un túnel dedicado en el `.env`
y ejecutar el mismo comando sin `api admin-web`. No reutilizar el túnel de Unraid
para una base local distinta: Cloudflare podría repartir peticiones entre ambos.

Se usa la versión publicada, no los cambios sin commit del directorio local.
Para desarrollo nativo consultar `DEPLOYMENT_README.md`; para probar el árbol de
trabajo con Docker, usar la validación aislada siguiente.

## Validación y versión instalada

```sh
python scripts/check_deployment.py
python scripts/check_deployment.py --published
```

La primera prueba empaqueta el árbol de trabajo; la segunda descarga desde GitHub
el SHA fijado en el mismo Compose. Ambas usan datos y credenciales sintéticos,
puertos libres y recursos temporales. Comprueban el túnel en la configuración,
arrancan API/panel y verifican login, perfil, imágenes, campañas, inscripciones,
pagos y persistencia después de reiniciar. No conectan un túnel real.

`source` y `web-build` deben acabar como **Exited (0)**, `api` y `admin-web` como
**healthy**, y `cloudflared` permanecer en ejecución con conexiones registradas.
Para consultar la referencia descargada y el túnel:

```sh
docker compose -f docker-compose.unraid.yml logs --tail 20 source
docker compose -f docker-compose.unraid.yml logs --tail 30 cloudflared
```

La API también puede comprobar el túnel desde la red interna:

```sh
docker compose -f docker-compose.unraid.yml exec api python -c "import urllib.request; print(urllib.request.urlopen('http://cloudflared:2000/ready').status)"
```

Un 200 indica que ese conector está conectado. Verificar además ambos dominios
públicos desde datos móviles: estar en ejecución no demuestra que las rutas
públicas estén correctamente configuradas.

## Actualización y rollback

Seguir [REDEPLOY_UNRAID.md](REDEPLOY_UNRAID.md). Guardar la configuración privada
y copiar los datos con el stack detenido antes de actualizar. Mantener el mismo
proyecto, rutas, secreto PAN y credenciales. No eliminar volúmenes.

La publicación se hace en dos commits: código validado y después la referencia
`SOURCE_REF` fijada a ese código. Así la plantilla nunca depende de una rama móvil.
No hace falta volver a generar plantillas.

Referencias: [interpolación de Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
y [arranque de servicios](https://docs.docker.com/reference/cli/docker/compose/up/).

# Despliegue con contenedores estándar y código desde GitHub

`docker-compose.deploy.yml` es el fichero autónomo de despliegue. No necesita el
checkout del repositorio en Unraid ni construir imágenes Docker personalizadas.
El `docker-compose.yml` original se conserva para desarrollar y probar cambios
locales todavía no publicados.

## Servicios

| Servicio | Imagen | Función |
| --- | --- | --- |
| source | python:3.12-slim | Descarga y extrae el archivo del commit de GitHub. |
| web-build | node:22-alpine | Instala con npm ci y compila el panel. |
| api | python:3.12-slim | Instala requisitos en un entorno persistente y ejecuta FastAPI. |
| admin-web | nginx:stable-alpine | Sirve el panel y aplica la configuración Nginx del repositorio. |
| cloudflared | cloudflare/cloudflared:latest | Túnel opcional con perfil tunnel y transporte HTTP/2. |

El código, la compilación y el entorno Python se almacenan en volúmenes separados
por versión. Los datos y certificados usan directorios persistentes del host.
Los servicios esperan a que termine la descarga/compilación y la API pase su healthcheck.
La descarga es del archivo de código de GitHub, no un `git pull` dentro de una
aplicación en funcionamiento.

## Preparación

1. Copiar **solo** `docker-compose.deploy.yml` al directorio de despliegue, por
   ejemplo `/mnt/user/appdata/loyalty-platform`.
2. Crear `data/certs` y copiar las credenciales reales: `google-sa.json`, `pass.p12`
   y `wwdr.pem`, según el proveedor. No guardar esos archivos en GitHub.
3. Crear un `.env` junto al Compose o definir sus variables en Compose Manager:

```dotenv
# SHA completo de un commit YA PUBLICADO que contenga estos cambios y scripts.
SOURCE_REF=REEMPLAZAR_POR_COMMIT_DE_40_CARACTERES
DATA_DIR=/mnt/user/appdata/loyalty-platform/data
CERTS_DIR=/mnt/user/appdata/loyalty-platform/data/certs
PAN_HASH_SECRET=REEMPLAZAR_POR_SECRETO_ESTABLE
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=REEMPLAZAR_POR_PASSWORD_LARGO
PUBLIC_API_URL=https://api.slmartinez.org
PUBLIC_ADMIN_URL=https://admin.slmartinez.org
GOOGLE_ISSUER_ID=TU_ID_DE_EMISOR
CLOUDFLARE_TUNNEL_TOKEN=TU_TOKEN
```

Mantener `PAN_HASH_SECRET` al migrar datos; cambiarlo rompe el matching de tarjetas.
Las credenciales y activación guardadas en la pantalla Wallet prevalecen sobre el
entorno. El alta de Google/Apple debe completarse en esa pantalla.
`DATA_DIR` y `CERTS_DIR` pueden omitirse para usar `./data` y `./data/certs`.
Los puertos locales pueden cambiarse con `API_PORT` y `ADMIN_PORT`.

El repositorio predeterminado es `slganimedes/Loyalty-platform`. `SOURCE_REF` es
obligatorio y debe ser un SHA de 40 caracteres, para fijar exactamente la versión.
`SOURCE_URL` permite usar un espejo del archivo fuente; normalmente se deja sin
definir y se descarga de `https://codeload.github.com/.../tar.gz/<SHA>`.
Los ejemplos no incluyen autenticación para repositorios privados.

## Arranque

```bash
docker compose -f docker-compose.deploy.yml config --quiet
docker compose -f docker-compose.deploy.yml up -d --wait --wait-timeout 600
docker compose -f docker-compose.deploy.yml ps -a
```

`source` y `web-build` deben terminar con código 0. `api` y `admin-web` deben
quedar saludables. La primera instalación requiere acceso a GitHub, Docker Hub,
PyPI y npm y puede tardar varios minutos.

Para activar el túnel:

```bash
docker compose -f docker-compose.deploy.yml --profile tunnel up -d --wait --wait-timeout 600
```

Usar `api:8000` y `admin-web:80` como destinos internos del túnel. Publicar los
logos para Google y los callbacks/downloads para Apple. Para exponer toda la API,
aplicar las restricciones de ingestión descritas en `Unraid_Cloudflare.md` a los
dos dominios; el proxy del panel también da acceso a `/api/v1/transactions`.
Los puertos de Compose se publican únicamente en loopback.

## Actualizar y restaurar

1. Crear una copia consistente de SQLite (con su API de backup o con la API detenida).
2. Detener la aplicación con `docker compose -f docker-compose.deploy.yml down`.
   **No usar `down -v`**: los volúmenes son persistentes.
3. Cambiar `SOURCE_REF` al commit publicado que se desea instalar.
4. Ejecutar de nuevo `up -d --wait --wait-timeout 600`.

El nuevo commit se descarga en un directorio propio y usa su propia compilación
y entorno Python. No se sustituye código bajo procesos que están ejecutándose.
La API aplica las migraciones de base de datos al arrancar. Para volver a una
versión anterior al modelo de campañas, restaurar también la copia de SQLite;
no basta con cambiar el commit. Restaurar la base no deshace notificaciones que ya
hayan recibido Google/Apple.

## Validación de cambios sin publicarlos

```bash
python scripts/check_deployment.py
```

Este comando crea un archivo local del código no ignorado por Git y lo sirve desde
un contenedor de prueba. Usa el mismo Compose, descarga, extracción, instalación,
compilación y arranque que producción, con credenciales sintéticas, puertos libres
y volúmenes aislados. Al terminar elimina solo los recursos de ese proyecto de
prueba. No publica código ni usa los datos o certificados reales.

**Los cambios locales no están disponibles desde GitHub hasta publicarlos.** No se
hará `git push` sin instrucción explícita del usuario. Mientras tanto, probar la
versión local con `docker-compose.yml`; para el despliegue remoto, elegir después
el SHA del commit que incluya este desarrollo. Un commit anterior sin
`scripts/start_api.sh` será rechazado por el inicializador.

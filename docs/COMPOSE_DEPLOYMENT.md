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


## Instalacion sin .env

La opcion recomendada para pegar el stack en Unraid es `docker-compose.install.yml`.
Es un Compose completo de contenedores estandar, sin `build`, sin `env_file` y sin
variables `${...}`. Los ajustes se concentran en `x-installation` y se reutilizan
mediante anclas YAML. `docker-compose.deploy.yml` sigue disponible para instalaciones
que prefieran gestionar variables externamente.

1. Copiar la plantilla a `docker-compose.private.yml` FUERA del repositorio de despliegue.
2. Editar `x-installation`: `SOURCE_REF` (SHA completo de un commit publicado con estos
   cambios), `PAN_HASH_SECRET`, usuario y password inicial, dominios y token del tunel.
   Generar secretos aleatorios; mantener PAN_HASH_SECRET si se reutiliza una base.
3. Ajustar DATA_MOUNT y CERTS_MOUNT a rutas absolutas de Unraid, por ejemplo
   `/mnt/user/appdata/loyalty-platform/data:/data` y
   `/mnt/user/appdata/loyalty-platform/data/certs:/certs:ro`.
4. Copiar los archivos Google/Apple necesarios al directorio de certificados. El
   Compose contiene rutas; no incorpora claves privadas ni certificados en el YAML.
5. Arrancar:

```bash
docker compose -f docker-compose.private.yml config --quiet
docker compose -f docker-compose.private.yml --profile tunnel up -d --wait --wait-timeout 600
```

Sin tunel, omitir `--profile tunnel`. La primera creacion de un administrador usa
el password indicado; modificarlo despues no cambia la cuenta ya creada. Los
proveedores se configuran y activan en el panel Wallet. Para un `$` literal en un
valor, escribir `$$` segun el escape de Docker Compose. No publicar el fichero
privado: contiene secretos; esta excluido en `.gitignore`. No ejecutar `config`
sin `--quiet` al compartir salidas, porque muestra la configuracion resuelta.

El codigo se descarga del commit fijado. Estos nuevos cambios necesitan publicarse
antes de usarlos desde GitHub; no seleccionar un commit anterior esperando el nuevo
comportamiento. La plantilla se regenera desde la configuracion canonica con
`python scripts/render_install_compose.py`. La prueba
`python scripts/check_deployment.py --inline` valida esta variante desde cero,
con archivo fuente local y recursos temporales, sin publicar codigo ni usar datos reales.

## Documentacion publica y Cloudflare

La API sirve una portada en `/`, Swagger UI en `/docs`, ReDoc en `/redoc` y el esquema
en `/openapi.json`, sin autenticacion para leer la documentacion. Las operaciones
administrativas siguen requiriendo autenticacion. Nginx tambien publica estos tres
recursos desde el dominio de administracion y el menu incluye un enlace.

Si el tunel de `api.slmartinez.org` solo publica logos, anadir una ruta para ese
hostname con Path `^/(docs(/.*)?|redoc|openapi[.]json)?$`, servicio HTTP `api:8000`.
Conservar la ruta de logos y el resto de rutas Wallet necesarias. El dominio admin
usa Path vacio y HTTP `admin-web:80`. Comprobar `/docs` y `/openapi.json` desde fuera.
Las restricciones de ingesta se mantienen en ambos dominios; publicar documentacion
no implica abrir indiscriminadamente todas las operaciones.


## Unraid: los cuatro botones del editor

Para Compose Manager usar `docker-compose.unraid.yml`: pegar TODO su contenido en
**Compose File**. Incluye un commit fuente fijado, rutas absolutas de appdata,
contenedores estandar y el tunel sin perfiles. No publica puertos del host y evita
conflictos con otras aplicaciones de Unraid. El acceso se hace por Cloudflare.

- **Compose File**: rellenar PAN_HASH_SECRET, BOOTSTRAP_ADMIN_PASSWORD,
  CLOUDFLARE_TUNNEL_TOKEN y GOOGLE_ISSUER_ID en x-installation. Conservar las anclas
  `&...` y referencias `*...`. SOURCE_REF ya apunta al codigo de esta version.
- **Env File**: dejar vacio. No hace falta .env.
- **UI Labels**: opcional. Para admin-web, Web UI = https://admin.slmartinez.org.
  Los iconos y demas etiquetas pueden quedar con sus valores predeterminados.
- **Stack Settings**: conservar las rutas del stack predeterminadas, sin fichero
  Compose o ENV externo. Activar Autostart si se desea inicio al arrancar el array.
  No necesita perfil ni comandos adicionales. Guardar y pulsar Compose Up.

Crear /mnt/user/appdata/loyalty-platform/data/certs y copiar google-sa.json.
Si se desean conservar los datos locales, copiar una copia consistente de SQLite
como data/loyalty.db y conservar PAN_HASH_SECRET y certificados. Con un directorio
vacio se crea una instalacion nueva; Wallet se activa desde su pantalla.

Configurar el tunel: admin.slmartinez.org -> HTTP admin-web:80; las rutas publicas
necesarias de api.slmartinez.org -> HTTP api:8000. Al trasladar el mismo tunel desde
el PC, detener el conector anterior cuando Unraid este preparado para servir, para
no repartir trafico entre dos bases de datos independientes.

source y web-build deben acabar con codigo 0; api y admin-web deben estar healthy,
y cloudflared conectado. Para regenerar el fichero Unraid tras publicar otra
version: python scripts/render_install_compose.py --unraid-ref SHA_COMPLETO.

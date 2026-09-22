# Unraid y Cloudflare Tunnel — slmartinez.org

El único archivo de arranque, tanto en Unraid como en local, es
`docker-compose.unraid.yml`. **Cloudflare arranca automáticamente** al ejecutar
Compose Up; no necesita un perfil adicional.

| Dominio público | Destino interno del túnel |
| --- | --- |
| `api.slmartinez.org` | `http://api:8000` |
| `admin.slmartinez.org` | `http://admin-web:80` |

## Instalación

1. En Cloudflare, crear/configurar el túnel y sus dos hostnames con esos destinos.
2. En Docker Compose Manager de Unraid, pegar el archivo completo en **Compose File**.
3. Rellenar los ajustes privados de `x-installation`, incluido
   `CLOUDFLARE_TUNNEL_TOKEN`. Conservar las rutas de datos y certificados existentes,
   el secreto PAN y la nueva referencia de código al actualizar.
4. **Env File** puede estar vacío. Si contiene variables anteriores, revisar que no
   sobrescriban `SOURCE_REF` o las rutas nuevas. Ejecutar **Compose Up**.
5. Esperar a API/panel saludables y comprobar conexiones registradas en cloudflared.

El túnel hace conexiones salientes. Los puertos de diagnóstico del host solo
escuchan en loopback, por defecto 18000 y 18080. No se requieren puertos abiertos
en el router. La red interna conecta Cloudflare con los servicios por nombre.

## Comprobación

Abrir ambos dominios desde datos móviles. El panel debe pedir usuario y contraseña;
`https://api.slmartinez.org/docs` debe cargar la documentación.
Con `AUTH_ENABLED=false` la API de negocio acepta llamadas anónimas, mientras
perfil y logout siguen requiriendo sesión. Las imágenes públicas de los pases
deben ser accesibles por Google/Apple sin una pantalla de login de Cloudflare.

Consultar los logs de cloudflared: un contenedor iniciado no garantiza conexión.
La ruta interna `http://cloudflared:2000/ready` devuelve 200 cuando el conector
está conectado; la guía Compose incluye el comando para comprobarlo desde la API.

Usar [COMPOSE_DEPLOYMENT.md](COMPOSE_DEPLOYMENT.md) para instalación/local y
[REDEPLOY_UNRAID.md](REDEPLOY_UNRAID.md) para actualizar conservando los datos.

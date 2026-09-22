# Campañas, asignación de pases y eliminaciones

## Modelo funcional

El comercio es propietario de sus clientes y campañas. **Cada pase nuevo pertenece
a una campaña y se asigna explícitamente a un cliente del mismo comercio**, para
Apple o Google Wallet. Un cliente puede tener pases de varias campañas y de ambos
proveedores. Solo puede existir una asignación activa por cliente, campaña y
proveedor. Repetir la asignación devuelve la existente.

Dar de alta un cliente, listar pases o registrar un pago no crea pases nuevos.
El motor aplica solo las campañas activas en las que el cliente tiene una inscripción
activa, independientemente de que haya instalado un pase. La asignación del pase no
reinicia el historial. El diseño y la selección de clientes se gestionan en la campaña.
Ver [diseños, inscripciones, migración y rollback](CAMPAIGN_DESIGNS.md).

Cada campaña tiene nombre. En Google se crea una clase por campaña y un objeto
por asignación. En Apple cada asignación tiene su propio número de serie y token.
El comercio proporciona la marca y el logo; no es el propietario funcional del pase.
Los pases de campañas muestran sus puntos o sellos y movimientos de esa campaña.
Los cupones existentes siguen siendo del cliente/comercio y se muestran como
información del cliente; este cambio no reasigna cupones a campañas.

## Asignar y dar de alta en el móvil

1. Crear el comercio, el cliente y una campaña activa con nombre.
2. Configurar y activar el proveedor Wallet con sus credenciales reales.
3. Entrar en **Pases Wallet**, seleccionar comercio, campaña, cliente y proveedor.
4. Pulsar **Asignar pase**. La asignación se guarda antes de contactar al proveedor.
5. Si el proveedor responde correctamente, se muestran la **URL de alta**, un enlace
   para abrirla y el **QR de alta en Wallet**. El QR se genera en el navegador sin
   enviar el enlace a servicios de QR externos.
6. Abrir la URL o escanear el QR con el móvil y confirmar el alta en Wallet.

El QR de alta contiene la URL de instalación. Es distinto del código QR que figura
dentro de la tarjeta, que identifica la inscripción mediante un token opaco. El endpoint
de verificación devuelve la relación cliente/campaña; no autoriza pagos. En modo
de prueba (`AUTH_ENABLED=false`) todos los endpoints admiten acceso sin credenciales.
Los enlaces Google firmados duran una hora; **URL y QR** genera un enlace nuevo.
Si falla el proveedor, la asignación permanece visible para reintentar con ese botón.
La URL solo se muestra cuando la generación o sincronización ha tenido éxito.

El logo debe ser accesible por HTTPS desde Internet. Los callbacks de Apple también
necesitan acceso público. En modo demo de Google, la cuenta del móvil debe tener
acceso al emisor o estar incluida como cuenta de prueba.

## Eliminar

| Elemento | Efecto |
| --- | --- |
| Pase | Bloquea nuevos enlaces, anula la asignación y notifica al proveedor. |
| Campaña | Desaparece del listado, deja de generar recompensas y anula todos sus pases. |
| Cliente | Desaparece del listado y del simulador, deja de ser identificado en nuevos pagos y anula todos sus pases. |

Los botones piden confirmación. Las bajas son lógicas: se conservan los registros,
identificadores y movimientos necesarios para la trazabilidad y las notificaciones.
No son un procedimiento de supresión de datos personales. Los códigos de cliente
eliminados permanecen reservados dentro del comercio.

Google recibe un `PATCH` del objeto con `state: INACTIVE`. Apple recibe la
notificación APNs; los dispositivos registrados pueden descargar la versión
firmada con `voided: true`. Se bloquean las nuevas instalaciones y los registros
de dispositivos para un pase anulado. Esto no borra físicamente la tarjeta del
teléfono: su propietario puede quitarla desde Wallet.

La intención de anulación se guarda antes de llamar al proveedor. Si este falla,
**Pases Wallet** muestra **Sincronización pendiente** y **Reintentar anulación**.
Un proceso de la API reintenta las bajas pendientes cada 30 segundos y al arrancar,
incluidas las de clientes y campañas ya eliminados. No hace falta volver a crear
el cliente o la campaña. Ejecutar una única instancia/worker de la API en este piloto.

Una asignación anulada no se reactiva por un pago ni por consultar sus enlaces.
Si cliente, campaña e inscripción siguen activos, puede asignarse explícitamente de
nuevo. Los GenericObjects de puntos reutilizan el identificador estable de la inscripción
una vez confirmada la anulación; Apple y los pases Loyalty antiguos crean otra asignación.

## Datos anteriores

La migración de SQLite conserva IDs de pases, tokens, registros de dispositivos,
saldos e historial. Retira la antigua restricción de un pase por cliente/proveedor
y permite asignaciones por campaña. Los pases anteriores, sin campaña, se muestran
como **Pase antiguo sin campaña**; conservan su comportamiento anterior hasta su
eliminación explícita. No se asignan automáticamente a una campaña elegida al azar.
Para sustituirlos: crear la asignación correcta y eliminar el pase antiguo.
Hacer copia consistente de `loyalty.db` antes de actualizar.

## API

- `POST /api/v1/merchants/{id}/campaigns`: incluye `name`.
- `GET /api/v1/merchants/{id}/passes`: lista asignaciones y estado, sin emitir enlaces.
- `POST /api/v1/customers/{id}/passes`: `{campaign_id, platform}`; devuelve pase y URL.
- `POST /api/v1/customers/{id}/passes/{pass_id}/link`: regenera URL para ese pase.
- `DELETE /api/v1/customers/{id}/passes/{pass_id}`: anula o reintenta la anulación.
- `DELETE /api/v1/customers/{id}`: baja del cliente y de sus pases.
- `DELETE /api/v1/merchants/{id}/campaigns/{campaign_id}`: baja de campaña y pases.

Con `AUTH_ENABLED=true`, estas operaciones requieren sesión y respetan el comercio del
administrador. Con `false`, cualquier visitante tiene acceso de administración para pruebas.
Los endpoints anteriores de consulta/refresh de pases solo trabajan con
asignaciones existentes; las claves de `pass_links` son el ID del pase para nuevas
asignaciones y el proveedor para los pases antiguos.

## Limpieza de la instancia existente (2026-09-20)

Por peticion expresa del propietario, se anularon los dos pases antiguos de Google
y, tras confirmar la respuesta satisfactoria del proveedor, se eliminaron sus
registros locales. No quedaban registros de dispositivos asociados. Se guardo
una copia consistente de SQLite antes de la operacion. No quedan pases sin
campana en esta instancia. La migracion generica sigue conservando los pases
antiguos de otras instalaciones hasta que se decida su anulacion.


## Baja completa de un comercio

Solo un superadministrador puede eliminar un comercio. El boton Eliminar abre un
resumen obtenido del servidor con el nombre y los totales de clientes, campanas,
pases, cupones y administradores vinculados, incluidos los registros ya dados de
baja. Tambien muestra cuantos pagos y movimientos se conservan como historial.
Cancelar no cambia nada. La confirmacion incluye una revision del resumen: si cambia
el conjunto de registros o el nombre antes de confirmar, la API devuelve 409 y se
debe volver a abrir el resumen.

La baja es logica, como en clientes y campanas: el comercio desaparece de los
listados y no puede reactivarse por PATCH. Todos sus clientes y campanas se dan de
baja, todos sus pases se anulan y los cupones pendientes se cancelan. Se cierran las
sesiones de sus administradores y se bloquean nuevos accesos. Los pagos nuevos se
rechazan. Se conservan historial y registros de Wallet necesarios para entregar la
anulacion y reintentar errores, incluso aunque el comercio ya no sea visible.
No se borran los registros de dispositivos Apple antes de que puedan descargar el
pase anulado. No se trata de una purga de datos personales.

- GET `/api/v1/merchants/{id}/deletion-preview`: resumen y revision.
- DELETE `/api/v1/merchants/{id}` con `{ "revision": "valor_del_resumen" }`:
  baja en cascada y numero de notificaciones pendientes.

No se han eliminado comercios reales como parte de la validacion del desarrollo.

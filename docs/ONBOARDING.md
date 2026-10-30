# Primer inicio en tu propio Docker

Cada instalación es independiente. No usa servidores, claves OAuth ni repositorios privados del mantenedor. Requiere Git y Docker con Compose v2; la primera construcción descarga dependencias. La interfaz pública usa el tema neutral hasta que el operador configure una identidad privada autorizada.

## Inicio rápido (macOS / Linux / WSL)

```sh
git clone https://github.com/joacoAviles/avia-social.git
cd avia-social
sh scripts/install.sh
```

El instalador genera `.env` con claves aleatorias sin necesitar Python en el host, inicia PostgreSQL, aplica migraciones y levanta app/worker. Muestra un código privado de instalación válido por 30 minutos. Abra http://localhost:8088/ y complete:

1. **Tu cuenta:** código, nombre, correo y contraseña del primer administrador.
2. **Tu marca:** nombre y zona horaria. No se crean las tres marcas AVIA automáticamente.
3. **Tus conexiones:** configurar y autorizar Google Calendar, Instagram, Facebook, YouTube y TikTok; opcionalmente vincular GitHub para identidad.
4. **Empieza a crear:** abrir el espacio o crear un borrador. Las conexiones pueden completarse después.

El código solo se almacena como hash, se consume dentro de una transacción con bloqueo y no se incluye en URLs. Se cierra el bootstrap al crear el primer usuario. Ni eliminar ese usuario ni conservar el código permite reclamar de nuevo la instancia. Si ya hay usuarios, la migración cierra el bootstrap y preserva cuentas existentes.

Si la construcción inicial se interrumpe después de generar `.env`, conserve ese archivo:

```sh
docker compose up -d --build --wait app worker
docker compose exec app python manage.py avia_setup_code
```

Este comando solo emite códigos si no hay usuarios ni una reclamación previa. Un código nuevo invalida el anterior. No es un mecanismo para resetear administradores ni un procedimiento de actualización.

En Windows sin WSL puede usar la instalación manual: `python scripts/setup.py`, `docker compose up -d --build --wait app worker` y `docker compose exec app python manage.py avia_setup_code`.

## Google Calendar no es YouTube

- **Google Calendar:** crea un calendario secundario «AVIA Social · Nombre de marca» en tu cuenta Google. Sincroniza desde AVIA las publicaciones con fecha y los eventos personalizados: crear, editar, mover o eliminar contenido en AVIA actualiza ese calendario. No lee tu calendario personal. El usuario ve ambos calendarios juntos desde Google Calendar. La conexión de YouTube se conserva por separado.
- **YouTube:** autorización independiente del canal para los adaptadores sociales. Credenciales por organización; permisos y revisión del proveedor siguen siendo necesarios.
- **TikTok:** client key/secret por organización y autorización de la cuenta mediante el flujo OAuth/PKCE existente.

Cada tarjeta muestra la dirección de retorno calculada desde el origen real de la petición. Configure primero el dominio/proxy/HTTPS si necesita callbacks públicos. Los formularios de secretos solo aceptan HTTPS o localhost; el proxy debe sanear cabeceras. El guardado de credenciales no comprueba que el proveedor las acepte: la tarjeta indica **Falta autorizar**. Una cuenta registrada muestra su estado guardado; no se presenta como prueba de publicación real.

Los secretos nunca se rellenan nuevamente en HTML. El acceso de edición exige permisos de marca y rol owner/admin de organización; Calendar global exige además superusuario. Cambiar credenciales puede afectar cuentas ya autorizadas de esa organización.

Guías de los proveedores: [Google OAuth web](https://developers.google.com/identity/protocols/oauth2/web-server), [YouTube OAuth](https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps), [TikTok Login Kit](https://developers.tiktok.com/doc/login-kit-web/).

## GitHub para identidad

Vincule `propietario/repositorio` con un token fine-grained limitado a ese repositorio, Contents: Read-only. El asistente comprueba acceso por GET a `api.github.com`, sin redirecciones ni URLs arbitrarias. No puede reducir ni certificar los permisos reales de un token emitido con acceso excesivo: el administrador debe limitarlo en GitHub. El token se guarda cifrado en PostgreSQL; no se copia al repositorio público ni a `.env`.

Se conserva el nombre canónico y la rama predeterminada obtenidos de GitHub. Después abra **Catálogo y revisiones**, sincronice y apruebe la identidad. Para sincronizar se requiere `brand/brand.yaml`, por ejemplo:

```yaml
schema_version: 1
brand:
  name: Mi marca
```

El manifiesto y los recursos en `brand/` y `assets/` quedan pendientes hasta aprobación. No se ejecuta código del repositorio. La comprobación de acceso no supone una sincronización ni aprobación. No se permite reemplazar el repositorio de una marca con historia por otro desde el asistente; se puede renovar el token del mismo repositorio. Cada fuente es única por instalación.

Las tres fuentes AVIA originales conservan compatibilidad con tokens montados en solo lectura. Otros instaladores pueden vincular sus propios repositorios explícitamente desde el onboarding. La apariencia corporativa de AVIA sigue teniendo su fuente privada específica; vincular una marca no modifica automáticamente el shell de la aplicación.

## Retomar y actualizar

Al completar la configuración inicial, el panel abre normalmente. **Guía de inicio y conexiones**, al pie de la interfaz, permite volver al asistente. Estado del onboarding, cuentas y secretos cifrados viven en PostgreSQL y sobreviven a recrear contenedores. Conserve las claves de cifrado y los volúmenes según [UPGRADES.md](UPGRADES.md).

El asistente no habilita `AVIA_PUBLISH_ENABLED` ni envía contenido. Autorizar cuentas puede activar las sincronizaciones heredadas. Antes de habilitar publicación, haga una prueba controlada por proveedor. Las pruebas automatizadas y la revisión visual del asistente no acreditan OAuth o publicación real en redes.

## GitHub paso a paso

**Dos repositorios distintos:** instala la aplicación clonando `https://github.com/joacoAviles/avia-social.git` (público, sin token). Para la identidad crea tu propio repositorio privado en [GitHub New repository](https://github.com/new). Copia [la plantilla mínima](../examples/brand-starter/brand/brand.yaml) a `brand/brand.yaml` y cambia `brand.name`. No clones los repositorios privados del mantenedor ni BrightBean para usar esta distribución.

1. En GitHub: foto de perfil → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
2. Pon nombre y caducidad; selecciona el Resource owner que contiene tu repositorio.
3. En Repository access selecciona Only select repositories y únicamente el repositorio de marca.
4. En Repository permissions: Contents → Read-only. Metadata de lectura viene incluido. No concedas escritura.
5. Genera el token, espera aprobación de la organización si corresponde y pégalo solo en AVIA → GitHub → Token de lectura.
6. En Repositorio escribe `propietario/nombre`. Pulsa Verificar y vincular, luego abre Catálogo y revisiones para sincronizar y aprobar.

Si caduca el token, genera otro con el mismo alcance y usa Renovar acceso. Nunca lo añadas al repositorio o a una captura. [Referencia oficial de GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## TikTok: administrador una vez, usuario por cuenta

El usuario debe poder pulsar **Conectar TikTok**, iniciar sesión y aceptar los permisos. No tiene que obtener un token manual. La instalación necesita antes una aplicación del proveedor: no distribuimos secretos de una aplicación compartida dentro del repositorio público.

1. El administrador abre [TikTok for Developers](https://developers.tiktok.com/) → Manage apps y crea o selecciona una aplicación.
2. Completa la información solicitada, añade Login Kit para Web y configura los productos/permisos necesarios para su uso. Login no equivale a permiso de publicación.
3. Abre AVIA desde su dominio HTTPS. Copia la dirección de retorno mostrada en la guía y regístrala en Login Kit. TikTok exige HTTPS y coincidencia exacta; `http://localhost:8091` no satisface ese requisito.
4. En Credentials copia Client key y Client secret al formulario AVIA y guarda. Usa las cuentas/entorno de prueba autorizados; completa la revisión del proveedor para producción.
5. El usuario pulsa Conectar TikTok, inicia sesión, acepta y vuelve a AVIA. Verifica la cuenta y su estado; publicación real requiere validación independiente.

[Requisitos oficiales de Login Kit web](https://developers.tiktok.com/docs/en/login-kit-web). Un servicio central de conexión podría reducir la configuración de cada instalación, pero sería otro servicio operado y aprobado, con disponibilidad y tratamiento de credenciales propios. No está implementado en esta versión.

## Instagram directo y Facebook

El asistente incluye ambas tarjetas independientes. Puedes configurar y autorizar Instagram directo sin completar Facebook, Google, TikTok o GitHub.

- **Instagram directo:** cuenta profesional (empresa o creador). El administrador configura Instagram API con Instagram Login en Meta for Developers y registra el callback HTTPS mostrado por AVIA. Guarda el Instagram App ID y su secreto correspondiente; el usuario pulsa Conectar Instagram directo e inicia sesión en Instagram. No requiere página de Facebook vinculada. La cuenta administrativa de Meta para registrar la aplicación es un requisito distinto de conectar una red a AVIA.
- **Facebook:** el administrador configura su aplicación y permisos de páginas, registra el callback mostrado y guarda App ID/App Secret. El usuario pulsa Conectar Facebook y autoriza las páginas que administra. No requiere conectar Instagram; no se ofrecen perfiles personales ni grupos.

Usa cuentas/roles de prueba autorizados por Meta y completa sus requisitos de revisión para usuarios externos y permisos solicitados. Los formularios guardan credenciales cifradas por organización usando los adaptadores existentes. Las pruebas automatizadas comprueban que Instagram se configura independientemente de Facebook; no acreditan autorización ni publicación real ante Meta.

## Conexión cotidiana y preparación administrativa

La pantalla Tus conexiones muestra tarjetas y botones OAuth para los proveedores habilitados. Los formularios de claves, callbacks y guías ya no se muestran en esa pantalla. «Administrar conexión» o «Habilitar … · administrador» abre la preparación de un solo proveedor; su acceso exige rol owner/admin y permiso para gestionar cuentas. La preparación de Google exige además superusuario.

Una vez guardadas las credenciales, vuelve a Tus conexiones y pulsa el botón del proveedor para iniciar sesión y consentir. Instagram directo funciona independientemente de Facebook. GitHub sigue siendo una fuente de marca opcional con token de lectura; no se anuncia OAuth GitHub, que no está implementado. Esta separación mejora el recorrido pero no elimina los requisitos del proveedor ni provisiona aplicaciones, dominios HTTPS o aprobaciones automáticamente.


## Configurar Calendar y resolver los bloqueos observados

1. Selecciona el proyecto correcto en Google Cloud. Habilita Google Calendar API en APIs y servicios → Biblioteca.
2. En Google Auth Platform → Audience (Público), añade como Test user el correo que usará Calendar si la aplicación está en Testing.
3. Configura el permiso `https://www.googleapis.com/auth/calendar.app.created`: permite crear y gestionar calendarios de esta aplicación sin acceso a calendarios personales.
4. En Clients (Clientes), crea un cliente web o añade la URI exacta mostrada por AVIA al cliente existente. No borres callbacks de YouTube. Calendar tiene su propio callback `/welcome/<workspace>/calendar/callback/`.
5. Guarda Client ID/secret en Habilitar Calendar. Pulsa Conectar Google Calendar y acepta el permiso. Después pulsa **Crear calendario AVIA y activar sincronización**.
6. En tu Google Calendar, activa «AVIA Social · Nombre de marca» en Mis calendarios para verlo junto al personal. No se copia contenido al calendario principal.

El worker sincroniza aproximadamente cada 120 segundos; también hay un botón Sincronizar ahora. Solo se sincronizan los espacios que el usuario sigue autorizado a administrar. Cambiar una fecha en AVIA actualiza el evento correspondiente; los cambios hechos directamente en Google no reprograman publicaciones en AVIA. Las publicaciones sin fecha no tienen una posición en Google. Cada destino social con fecha tiene su propio evento, además de los borradores con fecha propuesta y los eventos personalizados. Las publicaciones se representan como bloques de 30 minutos.

No se consulta CalendarList ni los eventos personales. La sincronización escribe únicamente en el ID de calendario creado por esta conexión. Los IDs de eventos son deterministas para evitar duplicados tras una respuesta perdida. Los eventos retirados conservan una referencia local para poder volver a crearlos con otro ID si se vuelven a programar. Un resultado incierto al crear un calendario detiene los reintentos automáticos y pide revisar Google antes de repetir. Desvincular detiene la sincronización y conserva el calendario remoto. No borres la base de datos o los identificadores de sincronización.

La autorización antigua de solo lectura, si llegó a usarse, no se convierte en permiso de escritura: requiere nueva autorización y crear un calendario exclusivo. La migración deja `managed=false` por defecto para impedir escrituras en calendarios seleccionados anteriormente.

**403 access_denied / solo testers (YouTube o Calendar):** añade el correo exacto en Audience → Test users del proyecto cuyo Client ID coincide con el error. No cambies a producción para evitar el bloqueo. Los refresh tokens en Testing para estos scopes suelen caducar a los siete días. Verifica el uso en producción antes de depender de programación continua.

**PROD01 con túnel SSH:** `localhost:8091` puede volver al servidor a través del túnel; mantén SSH abierto y usa el mismo navegador/puerto. La URI registrada debe coincidir exactamente. Para acceso estable configura HTTPS. TikTok exige HTTPS y no admite este callback HTTP.

**GitHub / Deploy keys:** esa pantalla pertenece a Settings del repositorio. Para el token abre los ajustes personales: https://github.com/settings/personal-access-tokens/new. Selecciona el repositorio de marca y Contents: Read-only; no necesitas una llave SSH.

Fuentes: [scopes Calendar](https://developers.google.com/workspace/calendar/api/auth), [creación de calendario secundario](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/insert), [OAuth web Google](https://developers.google.com/identity/protocols/oauth2/web-server).

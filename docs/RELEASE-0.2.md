# AVIA Social 0.2 — candidata de producción

## Cambios

- Instagram Unified Login separado de los dos conectores anteriores. Meta App ID + secreto + Configuration ID, OAuth con estado firmado y nonce; descubrimiento paginado de cuentas autorizadas. Guarda cifrado el contexto de portfolio/configuración con cada cuenta. Una autorización permite seleccionar varias cuentas por marca.
- Publicación de medios mediante Graph API v26.0 reutilizando el flujo de contenedores. La cuenta de destino se toma de la conexión seleccionada, nunca del primer activo del portfolio ni de un identificador enviado por el editor.
- Facebook Pages e Instagram vía Facebook: asistente de credenciales, selección múltiple y verificación de permisos de la marca al confirmar. Los perfiles personales de Facebook no son canales de publicación automática.
- YouTube: consulta de métricas y comprobación de conexión independientes del interruptor de publicación. El interruptor sigue bloqueando envíos. Diagnóstico sin secretos, actualización manual limitada a administradores de cuentas y tres solicitudes por hora.
- Los ceros recibidos siguen siendo ceros. Informes pendientes, permisos faltantes y API deshabilitada no se presentan como cero.

## Investigación y contrato consultado el 1 de noviembre de 2026

La documentación de [Meta: primeros pasos](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started) y [tokens](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/authentication) especifica `config_id`, `prompt=login`, intercambio servidor a servidor, `client_business_id` y `/me/assigned_instagram_accounts`. El token empresarial no se renueva con el intercambio de tokens de usuario del flujo anterior. Al vencer o revocarse requiere reconexión; no se implementó la API de gestión automática de tokens empresariales.

[Postiz](https://docs.postiz.com/self-host/providers/instagram) documenta actualmente Facebook Business y Standalone; ese instructivo no proporciona el contrato completo del flujo Unified Login nuevo. [Metricool](https://help.metricool.com/access-to-instagram-from-metricool-connection-types-and-differences-kcsrb) distingue conexión directa y vía Facebook, con capacidades e históricos diferentes. No se copió código ni se usaron sus credenciales; sus guías sirven de referencia para separar preparación administrativa de autorización del usuario.

## Configurar Instagram nuevo

1. Abre AVIA desde el dominio HTTPS de tu instalación.
2. Guía de inicio → Instagram · inicio de sesión unificado → Habilitar.
3. En Meta selecciona la configuración compatible con Instagram/SUAT. Para publicar necesitas `instagram_basic` e `instagram_content_publish`, además de lo obligatorio en la configuración de Meta.
4. Registra el callback que muestra AVIA, normalmente `https://TU-DOMINIO/social-accounts/callback/instagram_unified/`. El callback anterior `/instagram_login/` no corresponde a este nuevo conector.
5. Guarda Meta App ID, secreto y Configuration ID exclusivamente en el formulario. Conecta, autoriza portfolio/activos y selecciona las cuentas.
6. En desarrollo usa tu cuenta profesional con el rol aceptado. Para terceros completa Advanced Access y modo activo según Meta.

No se migran automáticamente cuentas de los flujos anteriores. El historial y las credenciales originales se conservan.

## Actualización conservando datos

Antes de actualizar, respalda PostgreSQL, medios, `.env` y claves de cifrado en almacenamiento privado. Conserva las mismas claves; perderlas impide descifrar las conexiones existentes. Nunca uses `docker compose down -v`.

```sh
cd ~/avia-social
git pull --ff-only
docker compose up -d --build --wait app worker
docker compose exec -T app python manage.py check
docker compose exec -T app python manage.py showmigrations credentials social_accounts
```

Compose ejecuta las migraciones antes de iniciar los servicios. La nueva columna de contexto tiene un valor vacío para cuentas anteriores; no reescribe tokens ni elimina cuentas. Para retroceder usa el commit anterior y reconstruye los servicios; conserva la columna adicional en la base. Una restauración completa requiere un respaldo consistente de base, medios y configuración.

## Condiciones pendientes para declarar producción validada

Esta entrega es una candidata 0.2: las pruebas automatizadas no certifican los permisos reales de los proveedores.

- Completar una autorización real de Unified Login, verificar varias cuentas, publicación controlada y reconexión/revocación en una instalación de prueba.
- Unified Login todavía no ofrece inbox, webhooks ni métricas. El asistente lo indica; conectar no afirma esas capacidades.
- Verificar YouTube Analytics API habilitada, permiso concedido y primer informe almacenado. Confirmar cero frente a pendiente en el navegador.
- Verificar backup/restauración y actualizar primero una instalación de prueba. No se ha actualizado PROD01 ni PJUD como parte de esta entrega.
- X/Reddit y los demás conectores conservan sus requisitos y límites; no se certificaron publicaciones reales en todos ellos. WhatsApp Business sigue pendiente.

## Evidencia local

- Suite de regresión ampliada: 1.155 pruebas aprobadas.
- Cuentas, estado de conexión y Meta: 116 pruebas aprobadas.
- Contrato específico Unified Login: seis pruebas aprobadas, con HTTP simulado; no equivalen a una autorización real.
- Imagen Docker construida y arranque limpio en un proyecto Docker aislado: PostgreSQL, migraciones, app y trabajador correctos; `/health/` respondió `ok`.
- `manage.py check` sin incidencias y `makemigrations --check --dry-run` sin cambios pendientes.
- Diagnóstico de la instalación existente realizado sin modificar datos: no había informes YouTube; el resolvedor de credenciales rechazaba las consultas cuando la publicación estaba desactivada.

### Corrección del recorrido Meta (2026-11-01)

- Configuración inicial en tres pasos: preparar app, iniciar sesión, elegir cuentas.
- Formulario con destino explícito: no depende de conservar los parámetros de navegación para mostrar errores.
- Un POST inválido mantiene el proveedor y muestra los errores; nunca devuelve secretos al HTML.
- Guardar vuelve al mismo proveedor y muestra el botón de autorización, sin pasar por la lista completa.
- El enlace al editor se retira durante la configuración. La ayuda extensa queda desplegable.
- Verificación: 53 pruebas focalizadas pasan. La inspección de la instalación encontró cero credenciales Meta guardadas; no permite atribuir retrospectivamente la causa de los dos intentos fallidos. La autorización real sigue pendiente.

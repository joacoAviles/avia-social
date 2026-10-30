# AVIA Social 0.1

Gestión social autohospedada, derivada de [BrightBean Studio](https://github.com/brightbeanxyz/brightbean-studio), bajo **AGPL-3.0**. Marcas independientes, editor, calendario, aprobaciones y API, con identidad versionada desde repositorios privados de GitHub.

**Versión inicial para validación local. Ninguna red social se declara probada en vivo.** El envío real está desactivado por defecto. No incluye credenciales, logos, manifiestos ni documentos privados del AVIA Brand System.

## Instalación

Requisitos: Git, Python 3 para generar configuración, Docker Engine/Desktop y Docker Compose v2. Reserve inicialmente 4 GB de RAM y 5 GB de disco; mida el consumo antes de alojar junto a otros servicios. Construcción inicial requiere internet.

```sh
git clone https://github.com/joacoAviles/avia-social.git
cd avia-social
python3 scripts/setup.py
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
# Sustituya el correo por el usado en el paso anterior:
docker compose exec app python manage.py avia_bootstrap --email tu-correo@example.com
```

Abra **http://localhost:8088**, inicie sesión con ese usuario y seleccione una marca. El enlace **Identidad de marca** está al pie de la interfaz. El alta pública está cerrada. El usuario propietario puede invitar/asignar miembros; el correo saliente está desactivado en esta edición inicial. Puede crear usuarios mediante administración local.

```sh
docker compose ps
docker compose logs --tail=80 app worker migrate
curl -fsS http://localhost:8088/health/
```

PostgreSQL no publica puertos. La interfaz solo escucha en loopback. Los datos sobreviven a `docker compose down`; **no use `down -v` si quiere conservarlos**. El trabajador realiza las tareas internas heredadas; no conecte cuentas reales hasta revisar sus tareas de sincronización y permisos.

## Actualizaciones e instalación definitiva

Antes de conectar cuentas reales, revise la [auditoría previa a instalación](docs/PREINSTALL_AUDIT.md) y el [procedimiento de actualización](docs/UPGRADES.md). Los datos son persistentes, pero todavía falta validar respaldo integral, actualización entre releases y recuperación en el destino definitivo.

## Identidad privada

Las únicas fuentes admitidas son:

- `joacoAviles/joaco-avia-brand`
- `joacoAviles/avia-rockets-brand`
- `joacoAviles/acelerados-brand`

Cada una corresponde a un workspace distinto. Cree en GitHub un token fine-grained por repositorio, con **Contents: Read-only**, acceso exclusivo a ese repositorio y vencimiento. No use el token general de su cuenta. Guárdelos localmente en:

```text
secrets/joaco-avia-brand.token
secrets/avia-rockets-brand.token
secrets/acelerados-brand.token
```

El directorio se monta en modo lectura, no se incorpora a Git ni a la imagen Docker. En Linux los archivos deben ser legibles por UID 10001 del contenedor; por ejemplo propietario `10001`, archivo `0400`, directorio `0500`. Mantenga copias y permisos bajo control del administrador. El programa solo realiza GET a `api.github.com`, no ejecuta código del repositorio y no sigue redirecciones. La limitación de privilegios del token debe configurarse en GitHub; el programa no puede reducir los privilegios de un token mal emitido.

```sh
docker compose exec app python manage.py avia_sync_brands
```

Se lee `main` una vez y se fija el commit SHA completo. Se cataloga `brand/` y `assets/`, excluyendo archivos ocultos, symlinks, submódulos y archivos mayores de 5 MiB. `brand/brand.yaml` debe usar `schema_version: 1` y contener `brand.name`. Un cambio crea una revisión **pendiente**; el propietario o rol con `manage_workspace_settings` aprueba/rechaza en la interfaz. Los borradores de identidad no reemplazan la versión activa. Revisiones ya decididas no se reescriben. Para volver a una identidad anterior, revierta en GitHub y sincronice el nuevo commit.

La identidad aprobada gobierna nombre y colores del workspace; tipografías, estilo y catálogo se consultan en el panel. No se descargan ni sirven fuentes privadas automáticamente. Recursos aprobados se descargan autenticados y por SHA, con `no-store`; **no se copian automáticamente a la biblioteca pública de medios**. No se inventan logos o campos TBD. Los datos sincronizados se guardan únicamente en su PostgreSQL privado.

## Funciones y límites

| Área | Entrega 0.1 |
|---|---|
| Marcas y usuarios | Workspaces separados, roles heredados, fuentes GitHub únicas, auditoría de revisión |
| Identidad | Catálogo por commit, aprobación humana, descarga privada, nombre/colores desde fuente aprobada |
| Editor y calendario | Código heredado: borradores, medios, variantes por cuenta, aprobaciones, programación y vistas de calendario |
| Redes sociales | Adaptadores heredados; necesitan apps OAuth, permisos y prueba por plataforma. **Cero redes validadas en vivo en esta entrega** |
| API | API heredada `/api/v1/docs`; claves por workspace y permisos; lectura privada `/api/v1/brand/` |
| Webhooks | GitHub HMAC entrante con deduplicación; eventos de revisión salientes firmados mediante outbox |
| Rundeck | Job importable desactivado para sincronizar; no se modificó ningún servidor Rundeck |
| n8n | Perfil Compose opcional y guía; sin workflows activos ni integración real validada |
| ChatbotX | Contrato de extensión futuro; no instalado ni conectado |

No forman parte de la aceptación 0.1: bots, DM/WhatsApp automatizados, campañas de correo, IA/Whisper, CRM, analítica real, SSO corporativo y plugins ejecutables arbitrarios. Algunas pantallas heredadas pueden existir, pero no representan funciones nuevas verificadas de AVIA.

Para habilitar publicaciones, valide primero OAuth, cuenta de prueba, permisos, límites y aprobación editorial. Después cambie `AVIA_PUBLISH_ENABLED=true` y recree app/worker. La seguridad de envíos depende también de los permisos del workspace y de la plataforma. La opción no es un interruptor general de toda salida de red: las cuentas conectadas pueden iniciar sincronizaciones heredadas.

## API, webhooks y automatización

Cree API keys desde Organization → API Keys con el mínimo alcance. La emisión heredada exige al menos una cuenta conectada en la allowlist y la API exige HTTPS para bearer; el arranque local HTTP sirve para la interfaz, no habilita automáticamente integraciones API externas. `/api/v1/me/` permite verificar alcance; `/api/v1/brand/` exige `manage_workspace_settings` y devuelve solo la marca de la clave, con identidad aprobada. No inserte tokens en URLs ni archivos de workflow.

GitHub: configure `AVIA_GITHUB_WEBHOOK_SECRET` y `POST /brand-system/webhooks/github/` detrás de HTTPS. Se aceptan eventos push a main con firma SHA-256 y delivery UUID; solo registran `sync_requested`. Ejecute `avia_sync_brands` desde Rundeck para sincronización periódica. **El webhook no aprueba ni publica.**

Salida: configure `AVIA_OUTBOUND_WEBHOOK_URL` (HTTPS público controlado por usted) y `AVIA_OUTBOUND_WEBHOOK_SECRET`; ejecute:

```sh
docker compose exec app python manage.py avia_deliver_events
```

Se transmiten únicamente ID de evento, tipo, workspace y revisión; no identidad ni recursos. Firma `X-Avia-Signature-256` sobre el cuerpo exacto e `Idempotency-Key` estable. Hasta cinco intentos, uno por ejecución. El receptor debe deduplicar: puede recibir un evento otra vez si se interrumpe la conexión después de aceptarlo. No habilitado por defecto. Restrinja salida de red al receptor mediante firewall si lo expone a terceros.

Documentación: [auditoría y decisión de base](docs/UPSTREAM_AUDIT.md), [operación y seguridad](docs/OPERATIONS.md), [verificación](docs/VERIFICATION.md), [Rundeck](integrations/rundeck/brand-sync.yaml), [n8n](integrations/n8n/README.md), [ChatbotX](integrations/chatbotx/README.md).

## Desarrollo y licencia

Las dependencias Python están fijadas en `requirements.lock`; frontend usa `npm ci`. Las imágenes tienen versiones explícitas, no `latest`; las actualizaciones de seguridad requieren revisar y regenerar el lock. No se promete reproducibilidad bit a bit de paquetes del sistema operativo.

```sh
sh scripts/test.sh
```

Para pruebas use una instalación desechable o CI. El script obtiene la contraseña del entorno del contenedor sin imprimirla. No pruebe sobre una instalación productiva.

Conserve [LICENSE](LICENSE), [NOTICE](NOTICE) y los avisos originales. La interfaz ofrece el código fuente; al desplegar cambios debe ofrecer el código correspondiente a la versión que ejecuta. Los activos privados de marca no están licenciados ni distribuidos como parte de este código. [README original](UPSTREAM_README.md), solo como referencia del upstream; para instalar AVIA prevalece este documento.

## Apariencia AVIA

La interfaz usa componentes compartidos y una identidad corporativa cargada en ejecución desde el repositorio privado de Avia Rockets. Consulte [configuración de apariencia](docs/BRANDING.md). El clon público usa una apariencia neutra hasta disponer de una instantánea local o revisión aprobada; no distribuye los recursos privados.

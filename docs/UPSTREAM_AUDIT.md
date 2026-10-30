# Auditoría inicial de BrightBean Studio — 2026-10-30

Fuente: https://github.com/brightbeanxyz/brightbean-studio
Snapshot revisado: `1d11c52007a3f714979ff1b071d153e69a8c274a`.
Alcance: licencia raíz, empaquetado, permisos, modelos, rutas, autenticación API y trayectorias de publicación. No es una auditoría exhaustiva de todos los proveedores ni un pentest.

## Evidencia y decisión

- `LICENSE`: GNU AGPL v3, texto conservado sin modificación. `README.md` declara AGPL-3.0. Se conserva como `UPSTREAM_README.md`.
- `apps/workspaces/models.py`: workspace con organización, zona horaria y política editorial; reutilizado como marca.
- `apps/members/middleware.py` y `decorators.py`: resolución de membresía por workspace y permisos por rol. Los managers `for_org`/`for_workspace` son filtros explícitos, no aislamiento automático: toda ruta nueva verifica pertenencia.
- `apps/api/auth.py`: bearer, intersección con permisos actuales del emisor y limitación por workspace. Se reutiliza en API de identidad.
- `apps/publisher/engine.py`: bloqueos de filas, estados y reconciliación de publicaciones ambiguas. No se sustituyen por reenvíos ciegos. Se añade bloqueo predeterminado para AVIA.
- Compose original: credenciales PostgreSQL fijas y puerto 5432 público. Sustituido por configuración generada y red privada. Archivos originales en `docs/upstream-*` como referencia, no autoactivados.
- No había `.dockerignore`: se agregó exclusión de secretos, volúmenes, copias y entorno local.
- `config/urls.py` expone `media_library/` para descarga por proveedores: el catálogo privado de AVIA jamás usa esa carpeta. Tiene un endpoint autenticado independiente.
- Existe integración de servicio Intelligence opcional; se mantiene desactivada en AVIA. No se asume que software autohospedado elimine tarifas o aprobaciones de proveedores.

Se elige **proyecto derivado AGPL con snapshot explícito**, no fork GitHub con toda la historia: facilita identificar una instalación AVIA y revisar las modificaciones propias, conservando procedencia y avisos. Un fork facilitaría sincronización upstream, pero no resolvería por sí solo aislamiento de identidad, configuración insegura ni pruebas. No se reescribe la plataforma desde cero ni se re-licencia su código. GitHub puede mostrarlo como repositorio independiente; jurídicamente se reconoce la derivación.

No se copió código de OpenPost ni ChatbotX. Su inclusión futura requiere auditoría separada de versión, licencia, contratos y permisos. Los tres repositorios privados se inspeccionaron en lectura para confirmar existencia y estructura de manifiesto; su contenido no se incorpora a fixtures ni documentación pública.

## Riesgos restantes

Los conectores sociales no fueron autorizados ni probados contra cuentas reales. Hay funcionalidades heredadas fuera del MVP, dependencias de terceros y recursos frontend CDN. Antes de internet: revisar actualizaciones de Django/dependencias, TLS, proxy confiable, almacenamiento público de medios, cuotas y restauración. El código AGPL y sus obligaciones de fuente deben acompañar las modificaciones; la titularidad/licencia de recursos privados de marca se administra por separado.

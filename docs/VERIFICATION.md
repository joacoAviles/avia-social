# Verificación de AVIA Social 0.1

Fecha: 2026-10-30. Entorno: Docker local/Colima ARM64, Python 3.12.12, PostgreSQL 16.10. Sin acceso ni modificaciones a PROD01/PJUD.

- Imagen construida desde Dockerfile con dependencias fijadas y frontend compilado.
- Migraciones aplicadas en base nueva, incluido `avia_brand/0001_initial`.
- App y PostgreSQL saludables; worker iniciado. `/health/` devuelve HTTP 200 y `{"status":"ok"}`.
- **779 pruebas aprobadas**: módulo AVIA (13), miembros, editor, calendario, aprobaciones, API, motor de publicación y rutas de medios. 515 avisos heredados, principalmente deprecaciones de Ninja y ausencia de staticfiles bajo el montaje de pruebas.
- Nuevas pruebas cubren acceso cruzado entre marcas, viewer sin permiso de escritura, revisión inmutable, identidad canónica, revisión de otra marca, recursos pendientes inaccesibles, sincronización idempotente, árbol truncado, allowlist de repositorios, integridad de blobs, firmas y replay de webhook, CSRF, bloqueo de publicaciones y outbox firmado sin reenvío tras éxito.
- Se agregaron y aprobaron cuatro pruebas adicionales: alcance y revocación de permiso API, bootstrap idempotente, GET exclusivo sin redirecciones y descarga aprobada privada. El módulo AVIA completo pasó **17/17**. La selección CI actual suma 783 pruebas.
- GitHubReader probado con fixtures sintéticos; el acceso real de sincronización requiere instalar tokens fine-grained Contents: Read-only. No se suministran tokens de producción.
- Se comprobó en lectura que los tres repositorios privados existen y se inspeccionó la estructura del manifiesto; no se copiaron recursos al repositorio público.
- Escaneo de secretos se realiza sobre el contenido versionado; `.env`, tokens y directorios privados se excluyen de Git y Docker. Los secretos generados de la instalación local no se distribuyen.

No verificado: OAuth ni publicación real en ninguna red; recepción/entrega contra proveedores sociales; servidor Rundeck; n8n activo; ChatbotX; TLS/dominio público; carga productiva; auditoría exhaustiva de dependencias o todos los módulos upstream. Las pruebas no demuestran permisos de Meta/Google ni entrega de publicaciones reales.

La CI reproduce la selección de pruebas, migraciones, validación Compose, construcción y arranque. Consulte el resultado del commit actual en GitHub Actions; un archivo de workflow no equivale por sí solo a una ejecución exitosa.

## Comprobación final

- La selección completa pasó dentro de la imagen final: **783 passed, 83 warnings**, 25.60 s. Se corrigió `scripts/test.sh` para ejecutar fixtures en un contenedor de pruebas efímero con permisos de escritura y admitir Compose v2 como plugin o binario independiente; no cambia UID 10001 de app/worker.
- Bootstrap y las tres páginas privadas se comprobaron contra PostgreSQL real con usuario sintético en una transacción revertida. No quedaron usuarios ni marcas sintéticos persistidos.
- App/worker reiniciados; health volvió a HTTP 200.
- La imagen no contiene `/app/.env` ni `/app/secrets`.
- CI Linux del código de aplicación `73c7331` aprobada: https://github.com/joacoAviles/avia-social/actions/runs/41119259777

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

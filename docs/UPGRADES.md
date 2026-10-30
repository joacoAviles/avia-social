# Actualizar conservando la instalación

Estado: procedimiento de operación para revisión; **no existe aún un actualizador automático validado ni un salto entre releases productivas ensayado**. Consulte [auditoría previa](PREINSTALL_AUDIT.md). No confunda instalación nueva con actualización.

## Responsabilidades del proyecto y de cada instalación

El mantenedor debe publicar releases identificables, cambios de configuración, migraciones, compatibilidad y pruebas de instalación/actualización/recuperación. Cada administrador conserva su configuración y credenciales, respalda sus datos y valida dominio/permisos de sus proveedores. Las actualizaciones del código no deben incorporar secretos del mantenedor ni reemplazar los de los usuarios.

No existe un dominio central obligatorio: localhost sirve para validación; las funciones que necesitan callbacks públicos requieren HTTPS propio y autorización del proveedor. La identidad corporativa privada no debe ser un requisito de arranque del clon público.

## Inventario persistente

Conservar nombre efectivo del proyecto Compose, contexto Docker, volúmenes PostgreSQL/media, `.env`, `secrets/`, archivos externos S3 si se usan y configuración de proxy/DNS. Si hay n8n, conservar también su volumen/clave; Rundeck tiene su propio respaldo. Conservar repositorios privados y su historia. Guardar secretos fuera de Git, cifrados y con recuperación probada.

No volver a ejecutar setup para reemplazar secretos. No borrar/recrear marcas, usuarios, apps OAuth o cuentas conectadas. No usar `down -v`, `volume prune` ni `system prune --volumes` en el host de instalación.

## Antes de actualizar

1. Identificar commit, imagen/ID y versión de PostgreSQL actualmente ejecutados. Guardar la imagen exacta y fuente correspondiente; `avia-social:0.1` es un tag mutable. Revisar cambios, dependencias y migraciones del destino. Evitar actualizar directamente a `main` sin una release aceptada.
2. Ensayar esa transición sobre copia aislada con salida de red bloqueada, sin worker, cron, n8n ni Rundeck activos. Una copia de producción conserva credenciales y tareas reales: `AVIA_PUBLISH_ENABLED=false` **no bloquea toda salida**.
3. Validar acceso de administración, lectura de tokens sin mostrarlos, cuentas, roles, agenda, medios y migraciones. Medir tiempos y espacio para dos versiones más respaldo. Aprobar ventana de mantenimiento y pérdida máxima de datos admisible.

## Ventana de actualización

1. Cerrar ingreso de escrituras, suspender disparadores externos y drenar tareas existentes. Confirmar fin de trabajos, locks y publicaciones inciertas. El worker atiende SIGTERM pero el plazo predeterminado de Docker puede matarlo antes de terminar; un simple `stop` no demuestra drenaje.
2. Con escritores detenidos, tomar copia coherente de PostgreSQL, media y configuración privada; registrar commit, imagen, versión del motor, hora y hashes. Cifrar y comprobar copia fuera del host. Verificar restauración antes de cambios destructivos.
3. Conservar el motor PostgreSQL durante una actualización normal de aplicación. Un cambio mayor de motor es otro procedimiento. Revisar nuevas variables sin sobrescribir las existentes.
4. Construir/seleccionar la nueva imagen. Ejecutar migraciones una sola vez, con app y worker anteriores detenidos. No confiar en `depends_on` como bloqueo de procesos ya activos. Si falla una migración, no arrancar servicios ni reintentar a ciegas.
5. Iniciar solamente la aplicación; comprobar esquema, salud, acceso, permisos, lectura de credenciales y archivos. Salud HTTP no demuestra toda la aplicación. Revisar agenda vencida durante la ventana.
6. Reanudar worker y disparadores únicamente tras conciliar cualquier envío incierto y comprobar funcionamiento. Registrar versión y resultado. Conservar copias anteriores según retención acordada.

## Recuperación ante fallo

No bajar simplemente el código sobre un esquema nuevo. Con servicios y salida externa detenidos, restaurar el conjunto coherente de **base + archivos + claves + imagen anterior** en destino aislado y verificarlo. Conciliar efectos externos ocurridos después del respaldo antes de ponerlo en servicio. El rollback puede perder cambios posteriores al respaldo; no es una reversión transparente ni garantiza cero duplicados.

## Criterio de aceptación

Una actualización se considera probada cuando una instalación con datos representativos conserva IDs, usuarios, permisos, conexiones cifradas, claves API, publicaciones programadas y medios; aplica migraciones; vuelve a servir; y permite una recuperación ensayada. Si el proveedor revoca un grant o exige nuevos scopes, la autorización humana sigue siendo necesaria.

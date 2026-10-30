# Operación

## Entorno aislado

Compose usa proyecto `avia-social`, volúmenes propios y puerto loopback 8088. No necesita PROD01, PJUD ni un Rundeck existente. No se desplegó en esos sistemas. Para otra instalación cambie COMPOSE_PROJECT_NAME y AVIA_PORT. Antes de compartir servidor mida CPU/RAM/disco, puerto, backups y permisos.

## Copias y restauración

Respalde `.env`, claves de cifrado y secretos en un almacén privado, separado del repositorio. La pérdida de SECRET_KEY/ENCRYPTION_KEY_SALT puede impedir recuperar tokens cifrados. Identidad sincronizada y tokens son datos privados de PostgreSQL. No adjunte dumps a issues.

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T postgres pg_dump -U avia -d avia -Fc > backups/avia.dump
docker compose exec -T postgres pg_restore --list < backups/avia.dump > backups/avia.toc
```

Copie también el volumen `media` (contiene medios de publicación) con el servicio detenido o un mecanismo de snapshot coherente. Cifre copias antes de moverlas. Pruebe restauración **en una instalación aislada**, con app/worker detenidos, base vacía y las mismas claves:

```sh
docker compose exec -T postgres pg_restore -U avia -d avia --no-owner --exit-on-error < backups/avia.dump
docker compose run --rm migrate
```

No use restauración sobre datos vivos. Retenga la imagen y commit anteriores, dump, claves y volumen antes de actualizar. Las migraciones existentes se ejecutan automáticamente; no revierta migraciones a ciegas. Rollback seguro: restauración coherente del backup y versión anterior en entorno detenido.

## Exposición pública

Configure dominio, HTTPS en proxy, `APP_URL`, `ALLOWED_HOSTS`, `AVIA_HTTPS=true` y orígenes CSRF según Django. Solo el proxy confiable debe alcanzar app; elimine encabezados reenviados aportados por clientes. Nunca exponga PostgreSQL. El modo local HTTP es deliberado y no equivale a despliegue público seguro. La limitación de intentos heredada usa caché local por proceso: despliegues con más de un worker necesitan caché compartida y limitación en proxy.

Los medios subidos a la biblioteca heredada son accesibles por URL para que las redes puedan descargarlos. No suba secretos ni documentos internos allí. Mantenga archivos de identidad en Brand System. Los recursos descargados desde el catálogo no se convierten automáticamente en medios publicables.

## Seguridad y extensión

No admite ejecutar scripts arbitrarios desde formularios, webhooks o repositorios. Automatice comandos conocidos a través de Rundeck con usuario/nodo dedicado. El job de ejemplo se importa desactivado y debe ajustarse a la ruta real. No monta socket Docker en la aplicación.

El contenedor corre como UID 10001; tokens GitHub se montan en solo lectura. Emita credenciales de solo lectura con vencimiento y alcance mínimo. El sistema no puede detectar todos los secretos escondidos dentro de un documento de identidad: los repositorios fuente deben tener revisión y secret scanning. La UI no interpreta manifiestos como HTML ni ejecuta YAML.

Los eventos salientes tienen entrega al menos una vez y límite de cinco intentos; revisar fallos antes de restablecer contadores. No hay garantía exactamente una vez en redes externas. La aprobación activa un commit concreto; los hashes de blobs se verifican antes de servirlos.

Reporte vulnerabilidades en privado mediante GitHub Private Vulnerability Reporting si está habilitado, o el canal privado que acuerde con el mantenedor. No publique tokens ni datos de clientes en issues. El SECURITY.md original se conserva como referencia upstream.

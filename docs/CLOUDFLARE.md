# Tu dominio HTTPS con Cloudflare

Este módulo opcional publica **solo AVIA Social** mediante un túnel con hostname estable. Necesitas un dominio activo en tu cuenta Cloudflare, acceso a Cloudflare One y permiso para publicar la instalación. No usa Quick Tunnels (direcciones temporales), no abre puertos del router y no monta el socket Docker. No crea cuentas, dominios o DNS automáticamente.

## 1. Preparar Cloudflare una vez

1. En Cloudflare One → Networks → Tunnels (también puede aparecer en Connectors), crea un túnel **Cloudflared**, por ejemplo `avia-social`, y selecciona Docker.
2. Guarda el token que aparece después de `--token`; no ejecutes el comando completo mostrado allí. AVIA lo pedirá de forma oculta.
3. Añade una **Published application route**: subdominio `social`, tu dominio, sin ruta adicional. Servicio **HTTP**, URL **app:8000**. No pongas localhost: apuntaría al contenedor del túnel. Deja HTTP Host Header sin sobrescribir para conservar el hostname público.
4. Activa **Always Use HTTPS** para ese hostname (puedes usar una regla específica si el dominio aloja otras aplicaciones). No apliques reglas de caché de HTML/API a AVIA. El tráfico público debe llegar por HTTPS; el tramo interno Docker usa HTTP.
5. No pongas una pantalla Cloudflare Access delante de callbacks/webhooks que deban recibir proveedores. AVIA mantiene su propio inicio de sesión y registro cerrado. Si utilizas Access, diseña y prueba sus excepciones explícitamente.

## 2. Preparar la instalación

Primero completa el alta del administrador en tu instalación local. Respalda según [UPGRADES.md](UPGRADES.md). Dentro de la carpeta del repositorio:

```sh
git pull --ff-only
python3 scripts/cloudflare_setup.py
docker compose up -d --build --wait app worker cloudflared
```

El asistente pide el dominio (ejemplo `social.tudominio.cl`) y el token, sin mostrarlo. Guarda `.cloudflare/tunnel.token` con permisos `0600`, fuera de Git y del contexto de construcción. Solo el servicio cloudflared monta ese archivo; no se pasa como argumento ni variable de entorno. Ejecuta el asistente con el usuario propietario de la instalación, sin sudo.

Actualiza `APP_URL`, hosts permitidos, HTTPS, UID/GID del conector y añade el perfil `cloudflare` a `.env`; conserva contraseñas, claves de cifrado, perfiles opcionales y datos. Hace una copia inicial privada en `.cloudflare/env.before-tunnel`. No ejecuta contenedores ni cambia Cloudflare por sí mismo. El hostname elegido sustituye la lista anterior de hosts públicos: esta configuración admite un dominio canónico por instalación.

El perfil queda persistido para los siguientes `docker compose up -d`. No necesitas volver a pegar el token después de actualizar. Usa el mismo proyecto Compose y sus volúmenes. El servicio no publica puertos; la aplicación mantiene el puerto loopback para diagnóstico. No expongas directamente el puerto 8000 ni añadas proxies no confiables: Django confía en `X-Forwarded-Proto` al habilitar HTTPS.

## 3. Comprobar y registrar los retornos

```sh
docker compose ps
docker compose logs --tail=40 cloudflared
curl -f https://social.tudominio.cl/health/
```

Sustituye el dominio. El contenedor iniciado no confirma conectividad: comprueba que Cloudflare muestre el túnel Healthy, que el dominio abra AVIA, que puedas iniciar sesión y enviar un formulario. `health/` está exento de redirección para los controles internos; no confirma por sí solo cookies ni OAuth.

Abre **AVIA desde el dominio HTTPS**, entra en Guía de inicio y conexiones y copia el retorno exacto de cada proveedor. Por ejemplo:

- Facebook: `https://social.tudominio.cl/social-accounts/callback/facebook/`
- Instagram directo anterior: `https://social.tudominio.cl/social-accounts/callback/instagram_login/`
- YouTube: `https://social.tudominio.cl/social-accounts/callback/youtube/`

Comprueba siempre los valores que muestra la app. Calendar contiene el identificador del espacio y TikTok usa un alias: no los escribas de memoria. Añade los nuevos retornos al mismo cliente OAuth en Meta/Google; no borres las credenciales guardadas. Inicia una autorización nueva desde el dominio (las sesiones iniciadas en localhost no se trasladan). Las conexiones existentes permanecen en la base de datos, aunque un proveedor puede pedir reautorización.

HTTPS resuelve el requisito de URL; no confirma permisos, revisión de Meta ni compatibilidad con Unified Login/SUAT, que sigue pendiente. El túnel tampoco habilita publicación real por sí mismo.

## Diagnóstico y recuperación

- **1033 / túnel desconectado:** verifica el token y conectividad saliente del servidor; consulta el estado en Cloudflare. No imprimas el archivo del token en logs.
- **502:** la ruta debe ser `http://app:8000`, con app saludable y ambos servicios en el mismo proyecto Compose.
- **Bucle HTTPS:** verifica Always Use HTTPS, que el Host no esté sobrescrito y que Cloudflare entregue `X-Forwarded-Proto: https`.
- **400 / CSRF:** dominio del navegador, `APP_URL` y hosts permitidos deben coincidir; reinicia app/worker tras cambiar `.env`.
- **Meta rechaza el retorno:** copia el callback desde el dominio nuevo; revisa barra final, proveedor y aplicación Meta correcta.
- **Archivos grandes:** Cloudflare aplica límites de tamaño/tiempo según plan. Comprueba la carga de tus videos; el túnel no elimina esos límites.
- **Rotar token:** rótalo en Cloudflare, repite el asistente y ejecuta `docker compose up -d --force-recreate cloudflared`. Mantén el dominio para no cambiar retornos.
- **Desactivar:** `docker compose stop cloudflared`; deshabilita la ruta en Cloudflare. Edita `.env` para quitar solo `cloudflare` de `COMPOSE_PROFILES`, poner `APP_URL=http://localhost:8088`, `AVIA_HTTPS=false` y hosts locales. Recrea app/worker. Consulta la copia inicial para recuperar valores anteriores, pero no la restaures a ciegas si cambiaste claves después. No uses `down -v`.

Verificación del módulo: pruebas de preservación de secretos/perfiles, validación del dominio, configuración Docker y proxy HTTPS. No se ha creado un túnel real ni verificado OAuth de Meta en una cuenta del mantenedor.

Fuentes oficiales: [crear túnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/), [token desde archivo](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/).

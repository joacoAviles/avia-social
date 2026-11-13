# AVIA Social 0.3 — conexión Meta reconstruida

Objetivo: que la primera cuenta de Facebook/Instagram se conecte. Se reemplazó el flujo de 0.2 por el modelo que usa Postiz en producción.

## Cambios

- **Un asistente Meta** (`?step=connections&configure=meta`): Meta App ID/Secret alimenta Facebook Pages e Instagram vía Facebook; Instagram App ID/Secret alimenta Instagram directo. Muestra los tres callbacks exactos, la lista de casos de uso/permisos a agregar en Meta y un botón **Probar credenciales con Meta**.
- **Login clásico de Facebook** para Facebook e Instagram vía Facebook. Se ignora y elimina `config_id`; desaparece el selector de «flujo» y la tarjeta Unified/SUAT.
- **Permisos como Postiz**: Facebook `pages_show_list, business_management, pages_manage_posts, pages_manage_engagement, pages_read_engagement, pages_read_user_content (+read_insights)`; Instagram `instagram_basic, instagram_content_publish, instagram_manage_comments, instagram_manage_insights, pages_show_list, pages_read_engagement, business_management`. Los de bandeja (`pages_messaging`, `pages_manage_metadata`, `instagram_manage_messages`) solo si se activa «Pedir permisos de bandeja».
- **Descubrimiento de páginas** en `/me/accounts` + `/me/businesses → owned_pages/client_pages`, deduplicado, prefiriendo la entrada con token de página.
- **Verificación de permisos** con `/me/permissions` tras el login: si falta uno esencial, AVIA lo nombra y explica si se desmarcó o si la app no lo tiene.
- **Errores reales**: se acabó «Failed to connect account». Los errores de Meta se traducen a la acción (redirect_uri, secreto, Instagram App ID, rol de desarrollador, código reutilizado, Invalid Scopes); los tokens se redactan.
- **Callbacks a prueba de proxy**: con `AVIA_HTTPS=true` se construyen desde `APP_URL` (`OAUTH_PUBLIC_BASE_URL`).
- `python manage.py avia_meta_check`: diagnóstico por consola sin secretos.

## 0.3.1

- CSP `form-action` permite `*.facebook.com` e `*.instagram.com`. En Chile Meta redirige el diálogo a `web.facebook.com` y Chromium bloqueaba el formulario «Conectar» sin mostrar error.

## 0.3.2

- La bandeja ya no depende de `AVIA_PUBLISH_ENABLED`: con el interruptor apagado, la sincronización de comentarios y mensajes fallaba en silencio para todas las cuentas.
- Aviso visible en todas las pantallas cuando la publicación está desactivada (antes las publicaciones quedaban en «Scheduled» sin explicación).
- Permiso de Messenger (`pages_messaging`) separado de la bandeja de Instagram.

## 0.3.4 (incluye 0.3.3)

- El aviso de envío en pausa solo lo ven administradores y ya no muestra detalles de configuración del servidor.

## Actualizar desde 0.2

```sh
git pull   # o aplica el bundle
docker compose up -d --build --wait app worker
docker compose exec app python manage.py migrate
docker compose exec app python manage.py avia_meta_check
```

No hay migraciones nuevas. Las cuentas conectadas y credenciales se conservan; abre el asistente Meta y guarda una vez para limpiar `config_id`. Guía completa: [META-SETUP.md](META-SETUP.md).

## Verificación

Suite completa local con PostgreSQL 16. Las pruebas usan respuestas simuladas de Meta: no acreditan una autorización real, que debe hacerse con la app y cuentas propias siguiendo META-SETUP.md.

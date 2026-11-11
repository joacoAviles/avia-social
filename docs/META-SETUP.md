# Conectar Facebook e Instagram (AVIA Social 0.3)

AVIA 0.3 conecta Meta igual que Postiz: **una app de Meta**, inicio de sesión clásico de Facebook (sin `config_id`, sin Unified Login/SUAT) y, opcionalmente, Instagram directo con el ID de Instagram de esa misma app.

| Canal en AVIA | Login | Requiere página de Facebook | Credenciales |
|---|---|---|---|
| Facebook Pages | facebook.com/dialog/oauth | Sí (la publicas) | Meta App ID + App Secret |
| Instagram vía Facebook | facebook.com/dialog/oauth | Sí, vinculada al Instagram | Meta App ID + App Secret (los mismos) |
| Instagram directo | instagram.com/oauth/authorize | No | **Instagram** App ID + secreto |

## 0. Requisitos de la instalación

```dotenv
APP_URL=https://social.tudominio.cl
AVIA_HTTPS=true
ALLOWED_HOSTS=social.tudominio.cl,localhost,127.0.0.1,app
AVIA_LEGAL_OPERATOR="AVIA Rockets SpA"
AVIA_LEGAL_CONTACT_EMAIL=contacto@tudominio.cl
```

Recrea `app` y `worker`. Desde 0.3, con `AVIA_HTTPS=true` todos los callbacks se construyen desde `APP_URL`, aunque Cloudflare/Caddy entreguen la petición como `http` o con otro host. Comprueba con:

```sh
docker compose exec app python manage.py avia_meta_check
```

## 1. App en Meta (una vez)

1. developers.facebook.com/apps → **Crear app** → «Otro» → tipo **Empresa**.
2. **Casos de uso → Agregar**:
   - «Administrar todo en tu página» → Personalizar → *Agregar*: `pages_show_list`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_engagement`, `pages_read_user_content`, `read_insights`, `business_management`.
   - «Administrar mensajes y contenido en Instagram» → **Configuración de la API con inicio de sesión de Facebook** → *Agregar*: `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`.
   - (Opcional) mismo caso de uso → **Configuración de la API con inicio de sesión de Instagram** → copia *ID de la app de Instagram* y su secreto.
3. **Configuración de la app → Básica**: dominio de la app, `https://…/privacy/`, `https://…/terms/`, categoría. Copia App ID y App Secret.
4. **Inicio de sesión con Facebook → Configuración**: «Inicio de sesión con OAuth web» y «Forzar HTTPS» activos. URI de redireccionamiento válidos:
   - `https://social.tudominio.cl/social-accounts/callback/facebook/`
   - `https://social.tudominio.cl/social-accounts/callback/instagram/`
5. Instagram directo → configuración de inicio de sesión para empresas → URI de redireccionamiento:
   - `https://social.tudominio.cl/social-accounts/callback/instagram_login/`
6. **Roles de la app**: en modo desarrollo solo conectan personas con rol. Tu Facebook como Administrador. Tu Instagram como **Instagram Tester** y acepta en Instagram → Configuración → Apps y sitios web → Invitaciones de evaluador.

> «Invalid Scopes» en el diálogo = la app no tiene agregado ese permiso en un caso de uso. Se corrige en el paso 2, no quitando permisos del código.

## 2. AVIA

Guía de inicio → Conexiones → **Habilitar Facebook / Instagram** (abre el asistente Meta):

1. Pega Meta App ID + App Secret (y, si quieres, Instagram App ID + secreto). Guarda.
2. **Probar credenciales con Meta**: valida el par con un token de app, sin usuario.
3. **Conectar Facebook Pages** / **Conectar Instagram vía Facebook** / **Conectar Instagram directo**.
4. En Meta pulsa «Editar acceso» y marca la página y la cuenta de Instagram. Vuelves a AVIA y eliges las cuentas.

## Bandeja de mensajes (DMs y webhooks)

Desactivada por defecto para que la primera conexión no falle. Cuando agregues «Interactuar con clientes en Messenger» (`pages_messaging`), `pages_manage_metadata` e `instagram_manage_messages` a la app, marca **Pedir permisos de bandeja** en el asistente y vuelve a conectar.

## Qué hace AVIA si algo falla

- Lee `/me/permissions` tras el login y nombra cada permiso esencial que Meta no concedió, distinguiendo «lo desmarcaste» de «tu app no lo tiene».
- Busca páginas en `/me/accounts` **y** en tus portafolios comerciales (`/me/businesses → owned_pages / client_pages`), como Postiz.
- Traduce los errores de Meta (redirect_uri, secreto, ID de Instagram equivocado, rol de desarrollador, código reutilizado) a la acción concreta.

## Diferencias con 0.2

- Se retiró del asistente Instagram «inicio de sesión unificado» (SUAT). Para conectar los activos de tu propio negocio no sirve: Meta exige que el portafolio dueño de la app sea distinto del cliente. El conector sigue en el código para instalaciones que ya lo usaban.
- Los `config_id` guardados se ignoran y se eliminan al guardar el asistente.

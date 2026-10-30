# Auditoría de actualización y recuperación antes de instalar

Fecha: 2026-10-30. Base revisada: `27f9c6239ffd7f494f3f702e7501cce454741897`.

**Decisión: apto para validación local; todavía no aprobado para instalación productiva con cuentas reales.** No existe una garantía de software «perfecto». La aceptación se define por pruebas y condiciones concretas. No se instaló ni modificó nada en PROD01/PJUD. Esta revisión no es una auditoría exhaustiva de seguridad ni una certificación de proveedores sociales.

## Lo verdaderamente irrecuperable

1. **Perder las claves originales sin copia.** `SECRET_KEY` y `ENCRYPTION_KEY_SALT` derivan tanto la clave AES-GCM de los campos como el secreto HMAC de las API keys. La base de datos sola no permite recuperar tokens OAuth, credenciales de aplicaciones, secretos de segundo factor o códigos de recuperación. Las API keys existentes dejan de funcionar. Cambiar claves requiere un procedimiento explícito de recifrado y transición; no existe hoy un comando verificado para ello. `SECRET_KEY_FALLBACKS` de Django no resuelve estos campos personalizados. Véanse `apps/common/encryption.py`, `apps/api_keys/services.py`, `apps/accounts/models.py`.
2. **Perder datos o archivos sin respaldo.** Borrar volúmenes, ejecutar `down -v`, purgar registros o perder el disco sin una copia recuperable no se arregla actualizando el código. PostgreSQL y el volumen `media` contienen partes distintas de la información. El respaldo de uno no reemplaza al otro.
3. **Deshacer efectos externos.** Una publicación, mensaje o webhook ya aceptado por otro sistema no se deshace restaurando PostgreSQL. Volver a una copia antigua puede repetir trabajos pendientes y perder el registro de envíos posteriores a la copia. Antes de reactivar una restauración hay que conciliar publicaciones y eventos con los proveedores.
4. **Recuperar acceso revocado por terceros.** Actualizar AVIA no restaura permisos revocados, apps OAuth eliminadas o cuentas externas suspendidas. Puede ser necesaria una nueva autorización. No hay integraciones sociales reales verificadas en esta versión.

No es necesario terminar todas las funciones futuras antes de instalar. Diseño, pantallas, nuevas redes y funcionalidades pueden evolucionar; los cuatro puntos anteriores son los que exigen protección desde el primer uso.

## Decisiones que se pueden cambiar, pero necesitan preparación

| Elemento | Evidencia en el proyecto | Riesgo / tratamiento |
|---|---|---|
| Nombre de instalación y volúmenes | `compose.yaml`, `.env.example`: proyecto `avia-social`, volúmenes database/media/n8n | Cambiar `COMPOSE_PROJECT_NAME`, `-p` o contexto Docker puede seleccionar otros volúmenes y parecer una instalación vacía. Conservar identidad del proyecto y registrar los nombres efectivos. Migración explícita para renombrarlos. |
| Claves de cifrado | Derivación desde dos variables, sin anillo de claves | No regenerarlas al actualizar. Guardarlas cifradas en respaldo separado y comprobar lectura tras restauración. El setup ya rehúsa sobrescribir `.env`. |
| Contraseña PostgreSQL | Compose la pasa al servidor y al cliente | Editar `.env` no cambia la contraseña del usuario en una base ya inicializada. Rotación coordinada en PostgreSQL y clientes, en mantenimiento. No confundirla con las claves de cifrado. |
| Dominio, HTTPS y rutas | `apps/social_accounts/views.py::_build_redirect_uri` usa el origen de la petición; APP_URL se usa en otras URLs | Elegir dominio estable antes de registrar apps. Cambiar dominio exige revisar callbacks, proxy, URLs de medios, webhooks, CSRF, enlaces y emisor OAuth/MCP. No basta cambiar APP_URL. No necesariamente exige reconectar todas las cuentas; depende del proveedor y de mantener el mismo cliente. |
| Identidad de las aplicaciones OAuth | Credenciales por organización y configuraciones de entorno | Conservar propiedad, client IDs y permisos. Reemplazar la aplicación externa puede exigir consentimiento nuevo. No hay contrato verificado de migración de grants entre clientes. |
| PostgreSQL mayor | Imagen fijada a 16.10 | Un salto mayor requiere ensayo de dump/restore o pg_upgrade, compatibilidad y espacio; no cambiar solamente la etiqueta de la imagen. Revisar también parches disponibles antes del despliegue final. |
| Esquema de datos / rollback | 23 operaciones RunPython y 4 RemoveField en migraciones propias/heredadas | Son indicios de transformaciones, no 27 errores. Algunas inversas son noop. Revertir código no reconstruye campos eliminados ni necesariamente datos originales. Ensayar cada salto concreto sobre copia. |
| Orden de actualización | Servicio migrate con depends_on; app/worker pueden estar ejecutándose de una versión previa | `up --build` no es por sí solo una estrategia de mantenimiento. Detener escritores y automatizaciones, respaldar, migrar y comprobar antes de iniciar worker. No mezclar versiones contra un esquema incompatible. |
| Trabajos en curso | Worker maneja SIGTERM y espera tareas; Compose no declara stop_grace_period | Docker usa un plazo predeterminado de 10 s, potencialmente insuficiente. Definir ventana y drenaje según tareas reales; no asumir que esperar más garantiza ausencia de envíos inciertos. Revisar locks, trabajos y respuestas externas antes de reintentar. |
| Imágenes / versiones | Todas las construcciones locales usan `avia-social:0.1`; paquetes SO no fijados por digest | El tag se reemplaza. Guardar imagen exacta/ID y código anterior antes de actualizar. Preparar releases identificables y retención; un git checkout no garantiza recuperar el mismo binario. |
| Archivos / S3 | `STORAGES` local o S3; referencias persistidas | Pasar a S3 es posible copiando todos los objetos y conservando rutas/URLs o migrándolas. Verificar hashes, permisos y enlaces existentes; no basta cambiar el backend. |
| Biblioteca y confidencialidad | `config/urls.py::PUBLIC_MEDIA_PREFIXES` incluye media_library | La biblioteca admite lectura anónima por URL para descarga de redes. No confundir con el catálogo privado. Si se requieren borradores confidenciales, rediseñar autorización/URLs temporales antes de cargar esos datos. La URL difícil de adivinar no es control de acceso. |
| Identidad privada | BrandRevision guarda catálogo/manifiesto; descarga de assets usa GitHub por SHA | La base no contiene una copia completa de los assets. Conservar historia privada, acceso y respaldo de los repos fuente, además de `.env` y `secrets/`. Renombrar/eliminar repos o reescribir historia puede romper referencias. Mantener permisos UID 10001 en el destino. |
| Modelo de marcas | BrandSource.repository es unique; workspace es OneToOne | Actualmente cada repositorio corresponde a una sola marca/workspace por instalación. Si se requiere una misma marca en múltiples organizaciones, hace falta migración y nuevo control de acceso. |
| Usuarios y automatizaciones | API keys ligadas a workspace, usuario emisor, permisos y cuentas permitidas | Conservar UUIDs, membresías y asignaciones. Borrar/recrear usuarios o marcas puede revocar accesos por diseño aunque no se cambien tokens. Migrar entidades, no reconstruirlas manualmente. |
| Contratos API/webhook | API v1, firma y delivery IDs; outbox con reintentos | Conservar rutas, cabeceras, identificadores y compatibilidad de payload. Cambios incompatibles requieren versión y periodo de transición. Restaurar puede repetir eventos: deduplicación externa obligatoria. |
| n8n / Rundeck / ChatbotX | n8n tiene volumen separado; Rundeck solo ejemplo desactivado; ChatbotX futuro | Respaldar n8n incluyendo su clave, credenciales/workflows y estado; no lo cubre el dump de AVIA. Respaldar Rundeck por separado si se instala. Ninguno está validado como parte de una recuperación integral. |
| Zona horaria | Configuración por organización/workspace y fechas persistidas | Elegir zona IANA correcta; cambiarla puede alterar horarios percibidos y slots futuros. Revisar agenda y cambios de horario de verano antes de publicar. |
| HTTPS/HSTS, correo y escalado | Ajustes de producción heredados, cache local por defecto, correo desactivado | Verificar dominio/proxy antes de HSTS; más réplicas necesitan cache/límites compartidos. Preparar acceso administrador y recuperación de cuenta/correo, no depender de una sesión local. |
| Licencia y recursos | LICENSE/NOTICE AGPL y fuentes OFL; assets privados fuera del repo | Mantener avisos y acceso al código correspondiente en cada release. Cambiar diseño no elimina la procedencia ni convierte recursos privados en recursos distribuibles. |

## Pruebas efectivamente realizadas

- CI del commit auditado **aprobada**: https://github.com/joacoAviles/avia-social/actions/runs/41121131123 . Regresión local anterior: 881 pruebas aprobadas.
- Ensayo nuevo con PostgreSQL 16.10 en contenedor y red interna efímeros, sin puertos publicados, sin worker y sin credenciales reales. No se montaron los volúmenes de la instalación local ni los secretos privados.
- Creación de usuario, organización/workspace, credencial de proveedor, cuenta social sintética, API key y borrador. Dump formato custom, restauración en otra base vacía, ejecución de migraciones y verificación desde un nuevo contenedor de aplicación.
- **Aprobado:** mismos UUIDs, contraseña de usuario válida, secreto TOTP recuperable, credenciales y tokens OAuth descifrables, bearer API vigente, zona horaria y texto del borrador intactos.
- **Demostrado:** cambiar cualquiera de las dos claves impide descifrar los campos. La comprobación de API puede además producir un error de descifrado al cargar el usuario relacionado, en lugar de un simple rechazo de token. Recuperar las claves originales restaura la verificación. No se afirma rotación soportada.
- Entorno temporal eliminado al terminar; aplicación local existente conservada.

**Límites del ensayo:** misma versión de aplicación antes/después, datos ficticios y base pequeña. No demuestra una actualización entre dos esquemas diferentes, restauración de archivos/media, recuperación de secretos reales, recuperación en otro host/arquitectura, n8n/Rundeck, tiempos con datos reales, publicación OAuth ni recuperación después de un envío externo interrumpido. No se ha cerrado por tanto la aceptación integral.

## Condiciones para publicar una versión instalable estable

AVIA Social se distribuye como proyecto libre autohospedado: cada administrador lo instala en su propio Docker. No se requiere un servidor o dominio del mantenedor para publicar el producto. Hay dos responsabilidades distintas: el proyecto debe demostrar instalación limpia, actualización y recuperación; cada operador debe configurar y validar su propio entorno antes de conectar cuentas reales.

La falta de un destino del mantenedor no bloquea el desarrollo ni la distribución. Las condiciones de host, dominio, claves y proveedores de la tabla corresponden a cada instalación, no a una infraestructura central de AVIA.

| Condición | Estado |
|---|---|
| Host, capacidad, disco y dominio definidos; separación de PJUD | Pendiente de destino elegido y preflight |
| Custodia cifrada de claves/secretos, responsable y segunda copia | Pendiente de configurar y probar |
| Respaldo integral DB + media + secretos + imagen; restauración en destino alterno | DB sintética aprobada; conjunto completo pendiente |
| Release reproducible identificada, procedimiento y ensayo de upgrade/rollback | Procedimiento documentado; automatización y ensayo entre versiones pendientes |
| Drenaje y conciliación de trabajos durante mantenimiento | Pendiente con escenarios representativos |
| Dominio HTTPS, callbacks y permisos por cada plataforma que se usará | Pendiente; cero redes probadas en vivo |
| Clasificación de archivos: publicables frente a confidenciales | Comportamiento documentado; decisión de uso pendiente |
| Acceso de administración y recuperación, alertas, retención y revisión de dependencias | Pendiente para el entorno final |

No activar publicación ni automatizaciones reales hasta cerrar las condiciones aplicables. No es necesario instalar n8n/Rundeck/ChatbotX si no serán usados en el primer despliegue.

## Referencias verificadas

- [Nombres de proyectos Compose y precedencia](https://docs.docker.com/compose/how-tos/project-name/).
- [Compose stop_grace_period](https://docs.docker.com/reference/compose-file/services/#stop_grace_period): plazo por defecto y terminación forzada.
- [PostgreSQL: actualizaciones mayores y menores](https://www.postgresql.org/docs/16/upgrading.html).
- [Imagen PostgreSQL: inicialización y variables](https://hub.docker.com/_/postgres).
- [Django: migraciones y reversión](https://docs.djangoproject.com/en/5.2/topics/migrations/#reversing-migrations).
- [n8n: clave de cifrado propia](https://docs.n8n.io/hosting/configuration/configuration-examples/encryption-key/).

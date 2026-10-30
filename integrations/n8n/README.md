# n8n opcional
`docker compose --profile n8n up -d n8n` abre http://localhost:5688.
La imagen es una configuración opcional, no una integración validada ni software AGPL de AVIA.
Configure el propietario de n8n al primer inicio. No active workflows automáticamente.
Use HTTP Request hacia `http://app:8000/api/v1/` con una API key de alcance limitado
creada en Organization → API Keys. Consulte `/api/v1/docs` para rutas y esquemas reales.
Guarde el bearer en Credentials de n8n, jamás en un JSON exportado.
Para pruebas use lectura de workspace y borradores; no publicación.
El volumen n8n persiste la configuración. Antes de exponerlo, configure HTTPS y cookies seguras.

# Identidad visual de AVIA Social

La interfaz de producto tiene un sistema compartido para acceso, navegación, editor/calendario, catálogos, OAuth y portal. El nombre visible es AVIA Social; los avisos de procedencia y AGPL de BrightBean Studio se conservan. No se cambian prefijos de tokens, modelos ni identificadores de protocolo para evitar romper integraciones existentes.

## Fuente privada y separación de marcas

La identidad corporativa se obtiene exclusivamente de la carpeta `brands/avia-rockets` del repositorio privado `joacoAviles/Avia-Brands` (o, en instalaciones antiguas, de `joacoAviles/avia-rockets-brand`), fijando el commit y verificando el hash del manifiesto. No se incorpora el manifiesto privado, su paleta concreta ni recursos privados al repositorio público o a la imagen Docker. El código público incluye una apariencia neutra de respaldo y componentes que reciben colores en ejecución.

1. Si existe una revisión aprobada del origen Avia Rockets en Brand System, el shell usa esa revisión.
2. Para configurar la apariencia antes de conectar las marcas, el operador puede importar una instantánea local mediante la CLI GitHub autenticada:

```sh
python3 scripts/import_ui_brand.py
```

El script realiza únicamente GET a `brands/avia-rockets/brand/brand.yaml` de Avia-Brands y guarda `secrets/ui-brand.json`, excluido de Git y Docker. No guarda el token de `gh`. Use una credencial con Contents: Read-only y acceso exclusivo al repositorio. La herramienta no reduce los privilegios de una credencial emitida con permisos más amplios.

El archivo debe ser legible por UID 10001 dentro del contenedor y permanecer en el montaje de secretos de solo lectura. En Linux, ajuste dueño a 10001 y permiso 0400, con permiso de recorrido en el directorio. Ejemplo para la instalación local Docker:

```sh
docker run --rm --user 0 -v "$PWD/secrets:/private" avia-social:0.1 \
  sh -c 'chown 10001:10001 /private/ui-brand.json && chmod 400 /private/ui-brand.json && chmod 711 /private'
```

Repita el ajuste tras una nueva importación. La instantánea es una selección explícita del operador para la presentación, no una aprobación automática de activos publicables. El lector no sigue URLs de recursos ni permite CSS arbitrario: solo colores hexadecimales y familias tipográficas conocidas (Orbitron o Space Grotesk, ambas OFL y servidas localmente). Una instantánea inválida se descarta.

La apariencia de la aplicación no modifica nombres, colores, contenidos ni cuentas de Joaco Avia, Acelerados u otros workspaces. Tampoco aprueba sus catálogos ni activa publicación social.

## Recursos, licencias y límites

No existe un master de logo/favicons liberado en el catálogo privado revisado. La aplicación muestra el nombre en texto, sin recrear un símbolo. Se retiraron de la distribución los gráficos de marca heredados que la identificaban como el producto original. La aplicación no declara nueva geometría ni un logo oficial. Los colores/estilos derivados para estados hover y superficies son implementación de UI; no se presentan como un manual corporativo aprobado.

Las fuentes distribuidas son fuentes públicas con licencia SIL OFL, obtenidas de Google Fonts, no archivos del repositorio privado. Consulte `static/fonts/SOURCES.md` y sus avisos OFL. Se sirven localmente. La selección tipográfica de la marca conserva el carácter provisional del manifiesto hasta su validación corporativa; no convierte recursos faltantes en aprobados.

Para incorporar un logo real: registrar primero su versión, procedencia, derechos y estado released en el repositorio privado; después implementar su lectura privada con el alcance de distribución autorizado. No lo añada al repo público por comodidad.

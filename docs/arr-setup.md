# Configuración híbrida Sonarr, Prowlarr y Bazarr

Este flujo mantiene Hobby-Anime como puerta obligatoria de idioma. Sonarr no
debe importar una descarga hasta que `ffprobe` la haya promovido desde
`/data/torrents/quarantine` hacia `/data/torrents/verified`.

## Invariante de seguridad

```text
Prowlarr → Sonarr → qBittorrent/quarantine
                            ↓
                    Hobby-Anime + ffprobe
                     ├─ rejected
                     └─ verified → Sonarr scan → hardlink → media/anime
```

No habilites **Completed Download Handling** en Sonarr. Hobby-Anime ejecuta
`DownloadedEpisodesScan` después de validar el idioma y siempre solicita modo
`copy`, permitiendo que Sonarr use hardlinks sin interrumpir el seeding.

## 1. Primer arranque

Configura `LAN_IP` en `.env` con la IP local del NAS y levanta los servicios:

```bash
docker compose up -d qbittorrent jellyfin sonarr prowlarr bazarr
docker compose ps
```

Interfaces:

- Sonarr: `http://IP_DEL_NAS:8989`
- Prowlarr: `http://IP_DEL_NAS:9696`
- Bazarr: `http://IP_DEL_NAS:6767`

## 2. Sonarr

En **Settings → Media Management**:

1. Activa el renombrado.
2. Activa **Use Hardlinks instead of Copy**.
3. Añade `/data/media/anime` como única carpeta raíz.
4. Configura nombres de episodios y numeración de anime según tus series.

En **Settings → Profiles**:

1. Crea formatos personalizados para `audio-es`, `subs-es`, `castellano` y
   `latino` usando los mismos marcadores de `SPANISH_LANGUAGE_TERMS`.
2. Asigna mayor puntuación a audio español y después a subtítulos españoles.
3. Añade formatos negativos para `RAW`, `English only` y `no subs`.
4. Usa etiquetas de serie para elegir entre castellano, latino o subtitulado.
5. Configura un Delay Profile si quieres esperar entre 30 y 60 minutos para que
   aparezca una versión preferida antes de tomar la primera candidata.

En **Settings → Download Clients**:

1. Desactiva **Completed Download Handling**.
2. Añade qBittorrent con host `qbittorrent`, puerto `8080` y sus credenciales.
3. Usa la categoría `sonarr`.
4. No actives la eliminación automática de descargas completadas.

En qBittorrent crea la categoría `sonarr` con ruta
`/data/torrents/quarantine`. Hobby-Anime vigila tanto `hobby-anime` como
`sonarr`.

Copia la API key de **Settings → General → Security** a `.env`:

```env
SONARR_ENABLED=true
SONARR_API_KEY=...
```

## 3. Prowlarr

Configura únicamente fuentes que estés autorizado a utilizar.

En **Settings → Apps** añade Sonarr:

- Prowlarr server: `http://prowlarr:9696`
- Sonarr server: `http://sonarr:8989`
- API key: la clave de Sonarr
- Sync level: `Full Sync`

Copia la API key de Prowlarr y activa su diagnóstico:

```env
PROWLARR_ENABLED=true
PROWLARR_API_KEY=...
```

Los formatos personalizados de Sonarr deben exigir los indicadores españoles
que uses en `SPANISH_LANGUAGE_TERMS`. Este filtro es preliminar; `ffprobe`
continúa siendo la autoridad final.

Para evitar duplicados, usa Sonarr como fuente principal de seguimiento. Deja
`RSS_URLS` vacío o limitado a feeds curados que Sonarr/Prowlarr no cubran; no
registres la misma serie simultáneamente en ambos flujos.

## 4. Bazarr

Conecta Bazarr con Sonarr usando `http://sonarr:8989`. Configura español como
idioma requerido y limita sus rutas a `/data/media`; nunca apuntes Bazarr a
`quarantine` ni `verified`.

Copia su API key:

```env
BAZARR_ENABLED=true
BAZARR_API_KEY=...
```

Bazarr complementa una biblioteca ya validada. No reemplaza la puerta de idioma
de Hobby-Anime.

## 5. Activar Hobby-Anime

```bash
docker compose up -d --build hobby-anime
docker compose exec hobby-anime hobby-anime doctor
```

El diagnóstico debe confirmar:

- qBittorrent, Jellyfin, Sonarr, Prowlarr y Bazarr accesibles.
- Completed Download Handling desactivado.
- `/data/media/anime` registrado como raíz de Sonarr.
- Sonarr registrado como aplicación en Prowlarr.
- `ffprobe` disponible y cuarentena montada.

## 6. Prueba integral

1. Añade una serie de prueba en Sonarr.
2. Descarga un episodio autorizado con categoría `sonarr`.
3. Confirma que termina en `quarantine`.
4. Ejecuta:

   ```bash
   docker compose exec hobby-anime hobby-anime verify
   ```

5. Si cumple la política española, debe pasar a `verified`.
6. Sonarr debe crear el episodio en `/data/media/anime`.
7. Comprueba origen y destino con `stat`: ambos deben compartir inode.
8. Jellyfin debe detectar el episodio tras actualizar su biblioteca.

Una descarga rechazada debe quedar detenida, con categoría
`hobby-anime-rejected`, y nunca aparecer en la biblioteca.

## Almacenamiento y seeding

- `MINIMUM_FREE_SPACE_GB` bloquea nuevas descargas antes de llegar al umbral.
- Configura límites de ratio/tiempo en qBittorrent, no eliminaciones inmediatas.
- Conserva el torrent hasta que `hobby-anime status` muestre el import como
  `imported`.
- Un archivo importado mediante hardlink puede seguir sembrándose desde
  `verified` sin duplicar bloques en `media/anime`.
- Toda limpieza automática debe mantener desactivada la opción de borrar datos;
  elimina primero la tarea de qBittorrent y verifica después que el hardlink de
  Sonarr siga presente.

## Paneles y calendario

Sonarr proporciona watchlist, calendario, episodios faltantes, perfiles por
serie y estado de imports. Prowlarr muestra fuentes y sincronización; Bazarr
muestra subtítulos pendientes. El estado específico de la puerta española se
consulta con:

```bash
docker compose exec hobby-anime hobby-anime status
```

## Recuperación

Los imports fallidos permanecen en SQLite y se reintentan automáticamente:

```bash
docker compose exec hobby-anime hobby-anime import
```

No muevas manualmente archivos desde `verified` mientras exista un import
pendiente; Sonarr necesita la misma ruta que recibió mediante la API.

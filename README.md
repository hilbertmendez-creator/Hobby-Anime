# Hobby-Anime

Automatización local de medios con RSS, qBittorrent, Jellyfin, AniList y un LLM
opcional ejecutado mediante Ollama. El proyecto está pensado para un NAS Ugreen
con Docker Compose y no requiere servicios de pago.

> Usa únicamente feeds y archivos que tengas derecho a descargar. No expongas
> qBittorrent, Jellyfin ni Ollama directamente a Internet.

## Arquitectura

```text
Prowlarr ──> Sonarr ───────────────┐
RSS autorizado ──> filtro español ─┴─> qBittorrent ──> torrents/quarantine
                         │                                  │
                         └──> SQLite          ffprobe <─────┘
                                                     │
                                         torrents/verified ──> Sonarr
                                                                  │ hardlink
                                                                  ▼
                                                           media/anime

/volume1/data/media ──> auditoría mensual ──> AniList ──> Ollama opcional
           │                                      │
           ├────────────> Jellyfin                 └──> Telegram/webhook
           └────────────> Bazarr
```

`torrents/` y `media/` viven bajo `/volume1/data`. Sonarr monta esa raíz con la
misma ruta interna y crea hardlinks sin duplicar datos. Hobby-Anime mantiene la
puerta de idioma: Sonarr solo recibe la orden de importación después de que
`ffprobe` haya aprobado todos los videos.

## Funcionalidad incluida

- Filtrado RSS por resolución, grupo, términos requeridos, términos excluidos y
  antigüedad.
- Política española obligatoria con términos alternativos y grupos confiables.
- Cuarentena y validación de audio/subtítulos españoles mediante `ffprobe`.
- Rechazo seguro de pistas parciales como `forced`, `signs` o `songs`.
- Gestión de series, calendario, búsquedas, nombres y hardlinks mediante Sonarr.
- Fuentes centralizadas mediante Prowlarr y subtítulos post-import mediante Bazarr.
- Reintento idempotente de imports Sonarr fallidos.
- Inyección idempotente en qBittorrent y seguimiento de estados en SQLite.
- Reintento de entradas que fallaron; una entrada añadida no se duplica.
- Planificador diario y mensual mediante APScheduler.
- Auditoría de archivos de video y detección básica del último episodio.
- Consulta de estrenos de la temporada actual en AniList.
- Reporte determinista sin IA o reporte enriquecido por un modelo local Ollama.
- Notificaciones por webhook compatible con Slack y por Telegram.
- Comando de diagnóstico para base de datos, almacenamiento y red interna.

## Despliegue en el NAS

### 1. Preparar directorios

Conéctate al NAS por SSH, entra al repositorio y averigua el UID/GID del usuario
que administrará los archivos:

```bash
id
sudo PUID=1000 PGID=1000 ./scripts/setup-nas.sh
```

Si las rutas del NAS son diferentes:

```bash
sudo DATA_ROOT=/otra/ruta/data \
  CONFIG_ROOT=/otra/ruta/docker/hobby-anime \
  PUID=1000 PGID=1000 ./scripts/setup-nas.sh
```

El resultado esperado es:

```text
/volume1/data/
├── media/
└── torrents/
    ├── quarantine/
    └── verified/
```

Para comprobar que el NAS permite hardlinks:

```bash
touch /volume1/data/torrents/.hardlink-test
ln /volume1/data/torrents/.hardlink-test /volume1/data/media/.hardlink-test
stat /volume1/data/torrents/.hardlink-test /volume1/data/media/.hardlink-test
rm /volume1/data/{torrents,media}/.hardlink-test
```

Ambas líneas de `stat` deben mostrar el mismo inode.

### 2. Configurar variables

```bash
cp .env.example .env
chmod 600 .env
```

Edita `.env`:

- Ajusta `PUID`, `PGID`, `TZ`, `LAN_IP` y las rutas del NAS.
- Define uno o más feeds autorizados en `RSS_URLS`, separados por comas.
- Configura los filtros RSS.
- Sustituye todas las credenciales de ejemplo.

No guardes `.env` en Git; ya está ignorado.

### 3. Iniciar qBittorrent y Jellyfin

```bash
docker compose up -d qbittorrent jellyfin sonarr prowlarr bazarr
docker compose ps
```

Interfaces desde la red local:

- qBittorrent: `http://IP_DEL_NAS:8080`
- Jellyfin: `http://IP_DEL_NAS:8096`
- Sonarr: `http://IP_DEL_NAS:8989`
- Prowlarr: `http://IP_DEL_NAS:9696`
- Bazarr: `http://IP_DEL_NAS:6767`

Las versiones recientes de la imagen de qBittorrent imprimen una contraseña
temporal durante el primer arranque:

```bash
docker compose logs qbittorrent
```

En qBittorrent abre **Tools > Options**:

1. Cambia la contraseña Web UI y copia el mismo valor a
   `QBITTORRENT_PASSWORD` en `.env`.
2. Confirma que la ruta de guardado sea `/data/torrents/quarantine`.
3. No desactives la autenticación para redes externas.

En Jellyfin completa el asistente y crea una biblioteca que apunte a `/media`.

### 4. Iniciar el agente

```bash
docker compose up -d --build hobby-anime
docker compose exec hobby-anime hobby-anime init-db
docker compose exec hobby-anime hobby-anime doctor
```

`doctor` debe marcar `ok: true` para `database`, `media`, `qbittorrent` y
`jellyfin`. También puedes comprobar resolución DNS desde la red Compose:

```bash
docker compose exec hobby-anime getent hosts qbittorrent jellyfin
```

### 5. Probar la extracción e inyección

Primero ejecuta sin modificar qBittorrent:

```bash
docker compose exec hobby-anime hobby-anime daily --dry-run
```

Después prueba la inyección real con un feed y contenido autorizado:

```bash
docker compose exec hobby-anime hobby-anime daily
docker compose logs --since=10m hobby-anime
```

El torrent debe aparecer con la categoría `hobby-anime` y la ruta
`/data/torrents/quarantine`.

Cuando termine, ejecuta una verificación manual:

```bash
docker compose exec hobby-anime hobby-anime verify
```

El agente inspecciona todos los videos de la descarga. Si cada archivo contiene
audio español, subtítulos españoles completos o un subtítulo externo `.es.srt`
cuyo texto supera una comprobación conservadora de idioma, qBittorrent lo mueve
a `/data/torrents/verified` y asigna la categoría `hobby-anime-verified`. Si no
cumple, detiene el torrent, lo conserva en cuarentena y asigna
`hobby-anime-rejected`.

Con Sonarr habilitado, una descarga verificada se importa automáticamente en
`/data/media/anime` usando `DownloadedEpisodesScan` y modo `copy`, que permite
hardlinks sin interrumpir el seeding. Consulta la configuración obligatoria en
[`docs/arr-setup.md`](docs/arr-setup.md).

La validación es deliberadamente estricta: pistas sin etiqueta de idioma,
subtítulos parciales y metadatos ambiguos se rechazan. Esto evita importar
contenido incorrecto, aunque un archivo mal etiquetado por su publicador todavía
puede requerir revisión humana.

### 6. Activar IA local (opcional)

El reporte mensual funciona sin LLM. Para usar Ollama:

```bash
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
```

Cambia `OLLAMA_ENABLED=true` en `.env` y recrea el agente:

```bash
docker compose up -d --force-recreate hobby-anime
docker compose exec hobby-anime hobby-anime monthly
```

`qwen2.5:3b` reduce el consumo frente a modelos grandes, pero debes validar que
la CPU y RAM del NAS sean suficientes. Si Ollama no responde, el agente genera
automáticamente el reporte determinista.

## Configuración del agente

| Variable | Valor predeterminado | Uso |
| --- | --- | --- |
| `RSS_ENABLED` | `true` | Desactívalo cuando Sonarr sea la única fuente |
| `RSS_URLS` | vacío | Feeds separados por comas; obligatorio para el agente diario |
| `RSS_RESOLUTION` | `1080p` | Texto de resolución exigido |
| `RSS_GROUPS` | vacío | Acepta cualquiera de los grupos indicados |
| `RSS_INCLUDE_TERMS` | vacío | Exige todos los términos indicados |
| `RSS_EXCLUDE_TERMS` | vacío | Descarta si coincide cualquiera |
| `RSS_MAX_AGE_HOURS` | `72` | Evita importar todo el historial al iniciar |
| `SPANISH_ONLY` | `true` | Exige evidencia española antes de descargar |
| `SPANISH_LANGUAGE_TERMS` | variantes españolas | Coincidencia OR en título, descripción, categorías o magnet |
| `SPANISH_NEGATIVE_TERMS` | `raw,...` | Rechaza candidatos incompatibles |
| `SPANISH_TRUSTED_GROUPS` | vacío | Grupos cuya publicación implica español |
| `QBITTORRENT_SAVE_PATH` | `/data/torrents/quarantine` | Área aislada de descarga |
| `QBITTORRENT_VERIFIED_PATH` | `/data/torrents/verified` | Descargas verificadas |
| `QBITTORRENT_MOVE_TIMEOUT_SECONDS` | `300` | Espera máxima para confirmar la promoción |
| `QBITTORRENT_VERIFY_CATEGORIES` | `hobby-anime` | Categorías RSS/Sonarr sometidas a la puerta |
| `MINIMUM_FREE_SPACE_GB` | `100` | Bloquea nuevas descargas bajo este espacio libre |
| `SONARR_ENABLED` | `false` | Activa importación híbrida después de ffprobe |
| `SONARR_VERIFIED_ROOT` | `/data/torrents/verified` | Raíz permitida para escaneo Sonarr |
| `SONARR_MEDIA_ROOT` | `/data/media/anime` | Biblioteca final administrada por Sonarr |
| `IMPORT_RETRY_INTERVAL_MINUTES` | `30` | Reintento de imports fallidos |
| `VERIFICATION_INTERVAL_MINUTES` | `10` | Frecuencia del verificador |
| `FFPROBE_TIMEOUT_SECONDS` | `60` | Límite por archivo inspeccionado |
| `DAILY_HOUR` / `DAILY_MINUTE` | `3` / `0` | Hora local del agente diario |
| `MONTHLY_DAY` / `MONTHLY_HOUR` | `1` / `9` | Ejecución mensual (día entre 1 y 28) |
| `OLLAMA_ENABLED` | `false` | Activa el reporte con LLM local |
| `WEBHOOK_URL` | vacío | Webhook entrante con payload `{"text": "..."}` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | vacío | Notificación Telegram |
| `JELLYFIN_API_KEY` | vacío | Habilita el cliente de estado visto de Jellyfin (requiere `JELLYFIN_USER_ID`) |
| `JELLYFIN_USER_ID` | vacío | Usuario de Jellyfin cuyo progreso se consulta; obligatorio si `JELLYFIN_API_KEY` está definido |
| `JELLYFIN_LIBRARY_ID` | vacío | Restringe la consulta a una biblioteca (`ParentId`); si no se define, consulta todas las series |

APScheduler interpreta las horas usando `TZ`. La configuración completa y sus
valores seguros están en `.env.example`.

## Comandos

```bash
hobby-anime init-db
hobby-anime audit
hobby-anime daily --dry-run
hobby-anime daily
hobby-anime verify
hobby-anime import
hobby-anime status
hobby-anime rejections
hobby-anime approve <hash>
hobby-anime monthly
hobby-anime doctor
hobby-anime scheduler
hobby-anime watched
hobby-anime anilist-auth
hobby-anime push-anilist
```

El contenedor ejecuta `hobby-anime scheduler` de forma predeterminada.

`rejections` lista las descargas que la política de idioma rechazó (hash, nombre
y razón); acepta `--json` para consumo por scripts. `approve <hash>` fuerza la
promoción de una o más descargas rechazadas: mueve el torrent a `verified/`,
reanuda el seeding, la registra como verificada con una nota de auditoría y, si
Sonarr está habilitado, encola la importación. `approve` **no** vuelve a
inspeccionar el archivo, así que usalo solo con descargas que confirmaste que
están correctamente etiquetadas.

## Estado visto (Jellyfin)

`hobby-anime watched [--json] [--series ID]` consulta, en modo solo lectura, el
estado visto/pendiente de cada serie en Jellyfin usando la API autenticada por
cabecera `X-Emby-Token` (la clave nunca viaja en la URL ni se registra en logs
o errores). Requiere las siguientes variables de entorno:

| Variable | Obligatoria | Uso |
| --- | --- | --- |
| `JELLYFIN_API_KEY` | Sí, para usar `watched` | Clave de API de Jellyfin |
| `JELLYFIN_USER_ID` | Sí, si `JELLYFIN_API_KEY` está definido | Usuario cuyo progreso se consulta |
| `JELLYFIN_LIBRARY_ID` | No | Restringe la consulta a una biblioteca (`ParentId`); sin definir, consulta todas las series |

Sin flags imprime una tabla legible con nombre de serie y episodios vistos/total
por serie. Con `--json` emite un único documento JSON:

```json
{
  "series": [
    {
      "series_id": "abc",
      "series_name": "Frieren",
      "episodes_total": 28,
      "episodes_watched": 12,
      "episodes": []
    }
  ]
}
```

`episodes` solo se completa cuando se pasa `--series ID`; en ese caso incluye el
detalle por episodio (`episode_id`, `episode_name`, `played`) de esa serie.
Errores de configuración o autenticación (clave/usuario faltante, 401/403) se
reportan con salida distinta de cero y nunca exponen el valor de la clave.

## Sincronización con AniList (push de progreso visto)

Dos comandos, ambos aditivos y separados del cliente anónimo `AniListClient`
usado por `monthly` para descubrimiento estacional:

- `hobby-anime anilist-auth` autoriza la app con tu cuenta de AniList vía
  OAuth2 (authorization-code grant) y guarda el token en la base de datos
  local (mismo archivo `chmod 0600` que el resto del estado). Requiere:

  | Variable | Obligatoria | Uso |
  | --- | --- | --- |
  | `ANILIST_CLIENT_ID` | Sí | Client ID de tu app registrada en AniList |
  | `ANILIST_CLIENT_SECRET` | Sí | Client secret de esa app (nunca se imprime ni se loguea) |
  | `ANILIST_REDIRECT_PORT` | No (`8712` por defecto) | Puerto local del callback OAuth; no puede coincidir con `STATUS_API_PORT` |

  El comando abre (o imprime, si no hay navegador disponible) la URL de
  consentimiento, levanta un listener HTTP efímero atado exclusivamente a
  `127.0.0.1` (un solo request, con `state` CSPRNG anti-CSRF y timeout), y al
  recibir el código lo intercambia por un access token que guarda en la
  tabla `anilist_token`. El `client_secret`, el código de autorización y el
  token nunca aparecen en la URL, en logs ni en mensajes de error.

- `hobby-anime push-anilist [--execute] [--yes] [--progress] [--json]`
  empuja el progreso visto (leído en modo solo lectura desde Jellyfin, igual
  que `watched`) hacia tu lista de AniList mediante mutaciones GraphQL
  autenticadas por `Authorization: Bearer`.

  **El modo por defecto es de solo vista previa (dry-run): sin `--execute`
  nunca se envía ninguna mutación a AniList.** Con `--execute`, el comando
  pide confirmación interactiva (`y/N`) antes de escribir; `--yes` omite
  **únicamente** esa confirmación, nunca sustituye a `--execute`.

  Por defecto solo se consideran las series **completamente vistas**
  (episodios vistos == total), que se marcan `COMPLETED` con el conteo total
  de episodios. Con `--progress` también se incluyen las series parcialmente
  vistas, que se marcan `CURRENT` con el conteo de episodios vistos.

  La identidad de cada serie (Jellyfin -> AniList) se resuelve con una regla
  híbrida y conservadora que nunca adivina:
  1. Un override manual persistido (tabla `anilist_mapping`) siempre gana.
  2. Si no hay override, se busca por título normalizado (case/puntuación/
     espacios insensibles, con marcadores de temporada como "Season 2"/"S2"/
     "2nd Season" removidos) y, si hay año disponible, se prioriza la
     coincidencia de año; solo se acepta el match automático si queda
     **exactamente un** candidato.
  3. Si hay cero candidatos o varios ambiguos (o desacuerdo de año sin
     candidato de año desconocido), la serie se omite (`skip_reason:
     "unmapped"`) y se reporta — nunca se envía a un id adivinado.

  Antes de escribir, el comando consulta la entrada actual en AniList
  (`get_list_entry`) y aplica una regla de idempotencia: si el estado y
  progreso ya coinciden, la serie se omite (`"unchanged"`) sin generar
  mutación; el progreso **nunca se hace retroceder** (si AniList ya reporta
  más progreso que el objetivo calculado, también se omite).

  Cada serie se procesa de forma aislada: si una mutación falla (error de
  red, HTTP, etc.), se registra como `failed` y el resto del lote continúa
  con normalidad. Las peticiones de escritura se pausan (~0.7s entre cada
  una) para respetar el límite de tasa de AniList (~90 req/min), y una
  respuesta `429` se reintenta respetando el header `Retry-After` (o backoff
  exponencial si no está presente) hasta 3 veces antes de marcar la serie
  como fallida.

  Sin flags imprime una tabla legible por serie (empujada, omitida con
  motivo, o fallida) y un resumen de conteos. Con `--json` emite un único
  documento:

  ```json
  {
    "executed": false,
    "pushed": 1,
    "skipped_unchanged": 0,
    "skipped_unmapped": 0,
    "failed": 0,
    "errors": [],
    "candidates": [
      {
        "series_id": "abc",
        "series_name": "Frieren",
        "media_id": 154587,
        "source": "auto",
        "status": "COMPLETED",
        "progress": 28,
        "skip_reason": ""
      }
    ]
  }
  ```

  Un token ausente o vencido (`anilist-auth` nunca ejecutado, o token
  expirado) produce un error claro que indica correr `anilist-auth`, con
  salida distinta de cero y sin exponer el valor del token en ningún caso.

## Desarrollo local

Requiere Python 3.11 o posterior:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
```

Ejemplo sin Docker:

```bash
cp .env.example .env
set -a
source .env
set +a
hobby-anime daily --dry-run
```

## CodeGraph para Cursor

El repositorio incluye `.cursor/mcp.json` para iniciar el servidor MCP de
CodeGraph sobre el workspace activo. El índice SQLite es local y está excluido
de Git mediante `.codegraph/.gitignore`.

Instala la CLI en cada equipo de desarrollo:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Inicializa y comprueba el índice desde la raíz del repositorio:

```bash
codegraph init
codegraph status
codegraph query run_daily
codegraph impact run_daily
```

Reinicia Cursor después de instalar la CLI. En **Settings > Tools & MCP** debe
aparecer el servidor `codegraph`. La configuración utiliza
`${workspaceFolder}`, por lo que funciona aunque el repositorio se clone en una
ruta diferente. La telemetría está desactivada para el proceso MCP; para
desactivarla también en invocaciones manuales:

```bash
codegraph telemetry off
```

CodeGraph mantiene el índice sincronizado mientras el servidor MCP está activo.
Si fuera necesario reconstruirlo por completo, ejecuta `codegraph index`.

## Gentle AI para Cursor

El proyecto usa el preset `minimal` de Gentle AI con alcance de workspace y
persona `neutral`. Esto añade memoria persistente mediante Engram y reglas
didácticas sin instalar GGA, temas, permisos globales ni proveedores externos.
La entrada `engram` convive con CodeGraph en `.cursor/mcp.json`.

Instala el binario oficial en cada equipo:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/Gentleman-Programming/gentle-ai/main/scripts/install.sh \
  | bash
export PATH="$HOME/.local/bin:$PATH"
```

Para registrar o actualizar este workspace:

```bash
GENTLE_AI_NO_SELF_UPDATE=1 gentle-ai install \
  --agent cursor \
  --preset minimal \
  --persona neutral \
  --scope workspace
gentle-ai doctor
```

Reinicia Cursor y confirma en **Settings > Tools & MCP** que `engram` y
`codegraph` estén activos. El diagnóstico puede indicar que Engram no responde
cuando Cursor está cerrado, porque el servidor MCP todavía no está ejecutándose.
Los avisos sobre GGA, Claude Code u OpenCode también son esperables con este
preset y no afectan la integración de Cursor.

Comandos útiles:

```bash
gentle-ai version
engram version
gentle-ai sync --dry-run
```

Gentle AI guarda su estado y respaldos en `~/.gentle-ai`; no contienen código
del proyecto y no se confirman en este repositorio.

## API de estado JSON

El servicio opcional `hobby-anime-api` expone dos rutas de solo lectura para
consultar el pipeline desde la LAN, documentadas automáticamente vía OpenAPI
3.1 (`/docs`, `/openapi.json`):

- `GET /status` → los mismos contadores que `hobby-anime status`
  (`rss`, `verification`, `import`).
- `GET /health` → los mismos chequeos que `hobby-anime doctor`, cada uno con
  `ok` y `detail`. Responde siempre `200 OK`; un chequeo degradado se refleja
  en el payload (`ok: false`), no en el código HTTP.

Ambas rutas exigen el header `X-API-Token` con el valor de la variable de
entorno `STATUS_API_TOKEN`. Si esa variable no está definida, el servicio se
niega a arrancar (falla cerrado; nunca sirve sin autenticación).

```bash
# .env
STATUS_API_TOKEN=un-token-largo-y-aleatorio

docker compose up -d hobby-anime-api
curl -H "X-API-Token: un-token-largo-y-aleatorio" http://IP_DEL_NAS:8787/status
curl -H "X-API-Token: un-token-largo-y-aleatorio" http://IP_DEL_NAS:8787/health
```

El puerto publicado por defecto es `8787` (variable `STATUS_API_PORT`,
sobreescribible en `.env`). El servicio reutiliza la imagen existente y corre
como proceso independiente del scheduler (`hobby-anime`); ninguno de los dos
afecta al otro.

## Operación y respaldo

- Crea una copia consistente de todas las bases y configuraciones con
  `sudo BACKUP_ROOT=/volume1/backups/hobby-anime ./scripts/backup-stack.sh`.
- El script detiene temporalmente los servicios, protege el backup con permisos
  restrictivos y vuelve a iniciarlos incluso si el proceso falla.
- Actualiza imágenes de forma controlada con `docker compose pull` y luego
  `docker compose up -d --build`.
- Revisa actividad con `docker compose logs -f hobby-anime`.
- Mantén los puertos publicados limitados a la LAN o detrás de una VPN.
- `ollama` ya viene fijado a una versión estable (`0.32.1`). El resto de las
  imágenes usan `latest` para facilitar el primer despliegue; para producción
  estable, fijá cada una al digest validado en tu NAS. Obtené el digest actual
  con `docker inspect --format '{{index .RepoDigests 0}}' lscr.io/linuxserver/sonarr`
  y ponelo en `.env` mediante la variable correspondiente, por ejemplo
  `SONARR_IMAGE=lscr.io/linuxserver/sonarr@sha256:<digest>`. Las variables
  disponibles son `QBITTORRENT_IMAGE`, `JELLYFIN_IMAGE`, `SONARR_IMAGE`,
  `PROWLARR_IMAGE`, `BAZARR_IMAGE` y `OLLAMA_IMAGE`.

### Backup remoto (offsite)

`scripts/backup-offsite.sh` sube el snapshot local más reciente (creado por
`backup-stack.sh`) a un remoto rclone, como redundancia offsite. Es opcional y
no modifica el flujo de backup local existente.

1. Configura un remoto con `rclone config` (el `rclone.conf` resultante y sus
   credenciales quedan bajo tu control; el script nunca los lee, escribe ni
   almacena).
2. Define `OFFSITE_RCLONE_REMOTE` con el destino completo, por ejemplo
   `gdrive:hobby-anime-backups`. Si la variable está vacía o no definida, el
   script registra un mensaje y termina sin ejecutar rclone.
3. Ejecuta el backup offsite solo después de que `backup-stack.sh` haya
   finalizado con éxito, para no subir un snapshot incompleto.

Ejemplo de entrada de cron en el host que encadena ambos scripts:

```bash
0 3 * * * cd /ruta/hobby-anime && ./scripts/backup-stack.sh && OFFSITE_RCLONE_REMOTE=gdrive:hobby-anime-backups ./scripts/backup-offsite.sh
```

Alternativa con systemd: dos unidades, con `offsite.service` declarando
`After=backup-stack.service` y `Requires=backup-stack.service`, disparadas por
un timer.

La subida usa `rclone copy` (nunca `rclone sync`), por lo que nunca borra
snapshots ya existentes en el remoto. Si `rclone` falla, el script registra el
error y termina con código distinto de cero sin reintentar.

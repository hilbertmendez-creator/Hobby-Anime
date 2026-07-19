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
```

El contenedor ejecuta `hobby-anime scheduler` de forma predeterminada.

`rejections` lista las descargas que la política de idioma rechazó (hash, nombre
y razón); acepta `--json` para consumo por scripts. `approve <hash>` fuerza la
promoción de una o más descargas rechazadas: mueve el torrent a `verified/`,
reanuda el seeding, la registra como verificada con una nota de auditoría y, si
Sonarr está habilitado, encola la importación. `approve` **no** vuelve a
inspeccionar el archivo, así que usalo solo con descargas que confirmaste que
están correctamente etiquetadas.

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

## Operación y respaldo

- Crea una copia consistente de todas las bases y configuraciones con
  `sudo BACKUP_ROOT=/volume1/backups/hobby-anime ./scripts/backup-stack.sh`.
- El script detiene temporalmente los servicios, protege el backup con permisos
  restrictivos y vuelve a iniciarlos incluso si el proceso falla.
- Actualiza imágenes de forma controlada con `docker compose pull` y luego
  `docker compose up -d --build`.
- Revisa actividad con `docker compose logs -f hobby-anime`.
- Mantén los puertos publicados limitados a la LAN o detrás de una VPN.
- Los valores `latest` facilitan el primer despliegue, pero para producción
  estable conviene fijar cada imagen al digest validado en tu NAS.

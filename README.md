# Hobby-Anime

Automatización local de medios con RSS, qBittorrent, Jellyfin, AniList y un LLM
opcional ejecutado mediante Ollama. El proyecto está pensado para un NAS Ugreen
con Docker Compose y no requiere servicios de pago.

> Usa únicamente feeds y archivos que tengas derecho a descargar. No expongas
> qBittorrent, Jellyfin ni Ollama directamente a Internet.

## Arquitectura

```text
RSS autorizado ──> agente diario ──> qBittorrent ──> /volume1/data/torrents
                       │
                       └──> SQLite (/config/hobby-anime.db)

/volume1/data/media ──> auditoría mensual ──> AniList ──> Ollama opcional
           │                                      │
           └────────────> Jellyfin                 └──> Telegram/webhook
```

El directorio `/volume1/data` se monta completo en qBittorrent. Así,
`torrents/` y `media/` pertenecen al mismo sistema de archivos y un organizador
puede crear hardlinks sin duplicar datos. Esta versión no mueve ni renombra
automáticamente una descarga terminada: evita copias y deja preparada la
estructura para crear el hardlink manualmente o integrar un organizador
posteriormente.

## Funcionalidad incluida

- Filtrado RSS por resolución, grupo, términos requeridos, términos excluidos y
  antigüedad.
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

- Ajusta `PUID`, `PGID`, `TZ` y las rutas del NAS.
- Define uno o más feeds autorizados en `RSS_URLS`, separados por comas.
- Configura los filtros RSS.
- Sustituye todas las credenciales de ejemplo.

No guardes `.env` en Git; ya está ignorado.

### 3. Iniciar qBittorrent y Jellyfin

```bash
docker compose up -d qbittorrent jellyfin
docker compose ps
```

Interfaces desde la red local:

- qBittorrent: `http://IP_DEL_NAS:8080`
- Jellyfin: `http://IP_DEL_NAS:8096`

Las versiones recientes de la imagen de qBittorrent imprimen una contraseña
temporal durante el primer arranque:

```bash
docker compose logs qbittorrent
```

En qBittorrent abre **Tools > Options**:

1. Cambia la contraseña Web UI y copia el mismo valor a
   `QBITTORRENT_PASSWORD` en `.env`.
2. Confirma que la ruta de guardado sea `/data/torrents`.
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
`/data/torrents`.

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
| `RSS_URLS` | vacío | Feeds separados por comas; obligatorio para el agente diario |
| `RSS_RESOLUTION` | `1080p` | Texto de resolución exigido |
| `RSS_GROUPS` | vacío | Acepta cualquiera de los grupos indicados |
| `RSS_INCLUDE_TERMS` | vacío | Exige todos los términos indicados |
| `RSS_EXCLUDE_TERMS` | vacío | Descarta si coincide cualquiera |
| `RSS_MAX_AGE_HOURS` | `72` | Evita importar todo el historial al iniciar |
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
hobby-anime monthly
hobby-anime doctor
hobby-anime scheduler
```

El contenedor ejecuta `hobby-anime scheduler` de forma predeterminada.

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

## Operación y respaldo

- Respalda los directorios de configuración y, como mínimo,
  `/volume1/docker/hobby-anime/agent/hobby-anime.db`.
- Actualiza imágenes de forma controlada con `docker compose pull` y luego
  `docker compose up -d --build`.
- Revisa actividad con `docker compose logs -f hobby-anime`.
- Mantén los puertos publicados limitados a la LAN o detrás de una VPN.
- Los valores `latest` facilitan el primer despliegue, pero para producción
  estable conviene fijar cada imagen al digest validado en tu NAS.

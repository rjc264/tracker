# CLAUDE.md

Contexto del repo para agentes de IA (Claude/Copilot) que trabajen en este proyecto.

## Qué es esto

Tracker de gastos bancarios (BAC Credomatic) que corre 100% en GitHub Actions
(sin servidor propio). Lee notificaciones de transacciones desde Gmail, las
parsea, las cifra y las publica en un dashboard estático en GitHub Pages.

No usa Docker (fue migrado deliberadamente de Docker a GitHub Actions).

## Arquitectura

```
Gmail API ──(cron diario)──> gmail_reader.py ──cifra (AES-GCM)──> data/expenses.enc.json ──commit──> GitHub Pages
```

- **`gmail_reader.py`**: script principal. Busca correos de `BANK_EMAIL` vía
  Gmail API (scope `gmail.readonly`) y parsea el formato real confirmado del
  correo "Alerta PRF BAC Credomatic" (texto plano linealizado desde una tabla
  HTML: `TABLE_MERCHANT_AMOUNT_RE`, `TABLE_STATUS_RE`, `CARD_LAST4_RE` — ver
  el comentario junto a esos regex para el formato exacto). `AMOUNT_RE` /
  `MERCHANT_RE` / `CARD_RE` genéricos quedan como **fallback** por si otro
  tipo de correo de BAC (transferencias, etc.) usa un formato distinto —
  aún no confirmado con un correo real, ajústalo si aparece.
  Transacciones con `Estado` != "Aprobada" (rechazadas/declinadas) se
  descartan en `parse_transaction` (no son gasto real).
  **El correo nunca dice si la tarjeta es de crédito o débito** — solo la
  marca y los últimos 4 dígitos —, así que `detect_transaction_type`
  primero consulta `CARD_TYPE_MAP` (variable opcional `ultimos4:tipo,...`,
  ver más abajo); si no hay mapeo cae a `tarjeta` (genérico) en vez de
  inventar crédito/débito. Cifra el resultado con `crypto_utils.encrypt_json`.
  Tiene retry con backoff (`execute_with_retry`) para el error de cuota de
  Gmail (`rateLimitExceeded`).
- **`crypto_utils.py`**: cifrado compartido (AES-GCM + PBKDF2-HMAC-SHA256,
  210,000 iteraciones). Debe mantenerse en espejo exacto con el descifrado en
  JavaScript dentro de `dashboard.html` (mismo formato de envelope: `salt`,
  `iv`, `iterations`, `ciphertext`, todo base64 excepto `iterations`).
- **`dashboard.html`**: página estática publicada en GitHub Pages. Pide la
  passphrase, deriva la clave con Web Crypto (`crypto.subtle`) y descifra
  `data/expenses.enc.json` en el navegador. Nunca hay backend ni login real:
  la "seguridad" es que sin la passphrase correcta el JSON es inútil. Incluye
  filtros dinámicos (fecha, tipo, comercio) que operan 100% en memoria sobre
  los datos ya descifrados. El botón "Buscar en Gmail" dispara un sync real:
  llama a la API de GitHub Actions (`workflow_dispatch` de `sync.yml`) con
  `since`/`until` desde el navegador usando un **Personal Access Token
  fine-grained** que el usuario pega en la sesión (guardado solo en
  `sessionStorage`, nunca persistido ni comiteado); luego hace polling del run
  vía la API de Actions y, al terminar, relee `data/expenses.enc.json` con la
  API de Contents (no espera a `pages.yml`). Como el repo es público, pedir
  este token en el cliente es un trade-off de seguridad consciente: el token
  vive solo en memoria del navegador de esa pestaña.
- **`.github/workflows/sync.yml`**: corre a diario (cron `0 13 * * *` =
  07:00 El Salvador) y por `workflow_dispatch` (acepta inputs opcionales
  `since`/`until`, `YYYY-MM-DD`, usados por el botón "Buscar en Gmail" del
  dashboard para acotar el sync a un rango de fechas). Escribe credenciales
  desde Secrets, corre `gmail_reader.py`, commitea `data/expenses.enc.json`
  si cambió, y dispara `pages.yml` manualmente (un push con `GITHUB_TOKEN` no
  dispara otros workflows automáticamente).
- **`.github/workflows/pages.yml`**: push-triggered (paths: `dashboard.html`,
  `data/expenses.enc.json`) + `workflow_dispatch`. Publica `dashboard.html`
  como `index.html` junto con el JSON cifrado.
- **`generate_token.py`**: script local de un solo uso para generar
  `token.json` vía OAuth y obtener los valores base64 para los Secrets.

## Secrets y Variables de GitHub (repo `rjc264/tracker`, público)

Secrets:
- `GMAIL_CREDENTIALS_B64`, `GMAIL_TOKEN_B64` — credenciales OAuth de Gmail.
- `DASHBOARD_PASSPHRASE` — passphrase usada para cifrar/descifrar. Write-only
  (no se puede leer de vuelta desde GitHub); si se pierde, los datos cifrados
  ya sincronizados no son recuperables.

Variables:
- `BANK_EMAIL` — remitentes reales separados por coma:
  `notificaciones_bac@baccredomatic.sv,info@baccredomatic.com`
- `BANK` = `BAC`
- `SYNC_DAYS` = `30` (default cuando el dispatch no manda `since`)

No son Secrets/Variables de GitHub, pero relevantes para `gmail_reader.py`:
- `SYNC_SINCE` / `SYNC_UNTIL` — rango explícito (`YYYY-MM-DD`), sobreescriben
  `SYNC_DAYS`. Los manda `sync.yml` desde `github.event.inputs.since/until`
  cuando el dashboard dispara el workflow manualmente; vacíos en el cron
  diario.
- `CARD_TYPE_MAP` (GitHub Variable opcional) — `"ultimos4:tipo,ultimos4:tipo"`
  (ej. `"8825:tarjeta_credito,4321:tarjeta_debito"`). El correo de BAC no
  distingue crédito de débito; esto es lo único que lo suple. Sin este mapeo,
  las compras con tarjeta quedan clasificadas como `type: "tarjeta"`
  (genérico) en vez de `tarjeta_credito`/`tarjeta_debito`.

## Convenciones importantes

- Nunca imprimir contenido de correos (subject/body) en logs de Actions: son
  públicos en un repo público y contienen datos financieros.
- Los valores de entorno opcionales se leen con `os.environ.get(X) or "default"`
  (no solo `.get(X, "default")`), porque GitHub puede pasar variables vacías
  en vez de no definidas, y `""` es falsy pero no dispara el default de `.get`.
- `data/expenses.enc.json` sí se versiona en git (a propósito, va cifrado).
- Los regex de parseo (`AMOUNT_RE`, `MERCHANT_RE`, `CARD_RE`) son genéricos y
  puede que necesiten ajustarse al formato real de los correos de BAC
  Credomatic si el parseo falla o extrae mal los campos.
- `detect_category` clasifica cada gasto (alimentacion/transporte/
  entretenimiento/viajes/salud/servicios/vivienda/compras/otros) por palabras
  clave sobre comercio+asunto+cuerpo (`CATEGORY_PATTERNS`, primera coincidencia
  gana). Es heurístico, no viene del banco: ajusta las listas de palabras al
  vocabulario real de tus comercios frecuentes. `main()` recalcula `category`
  para **todas** las transacciones (no solo las nuevas) en cada sync, usando
  merchant/subject ya guardados (el cuerpo del correo no se persiste), así que
  mejorar `CATEGORY_PATTERNS` reclasifica también el historial. El dashboard
  usa las mismas claves de categoría en `categoryLabels`/`categoryColors`
  (JS) — si agregas una categoría nueva en Python, agrégala también ahí.

## Comandos útiles

```bash
# Correr sync localmente
pip install -r requirements.txt
CONFIG_DIR=. DASHBOARD_PASSPHRASE="..." python gmail_reader.py

# Disparar workflows manualmente
gh workflow run sync.yml
gh workflow run pages.yml

# Ver estado de un run
gh run view <run-id> --json status,conclusion,jobs
gh run view <run-id> --log-failed
```

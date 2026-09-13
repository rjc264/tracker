# 💰 BAC Expense Tracker

Sincroniza automáticamente las notificaciones de transacciones bancarias (BAC)
desde Gmail hacia `data/expenses.json`, corriendo 100% en **GitHub Actions**
(no necesitas tener tu máquina encendida). Un dashboard estático se publica
en GitHub Pages para consultar los gastos desde cualquier lugar.

## ⚠️ Aviso de seguridad

Este repo es **público** (requisito de GitHub Pages en el plan gratuito), pero
`data/expenses.enc.json` se guarda **cifrado con AES-GCM** (clave derivada por
PBKDF2 desde una passphrase que solo tú conoces). Ni el repo, ni los Actions,
ni GitHub Pages guardan la passphrase en texto plano — solo vive en un
Secret de GitHub (usado para cifrar) y en tu cabeza (para descifrar en el
navegador). Si la pierdes, los datos no son recuperables.

## 🏗️ Arquitectura

```
Gmail API ──(diario, cron)──> gmail_reader.py ──cifra (AES-GCM)──> data/expenses.enc.json ──> commit
                                                                            │
                                                                            └──> GitHub Pages
                                                                                   (dashboard.html pide
                                                                                    la passphrase y
                                                                                    descifra en el navegador)
```

- `.github/workflows/sync.yml` — corre diario (`workflow_dispatch` también),
  lee correos de `BANK_EMAIL`, actualiza y vuelve a cifrar `data/expenses.enc.json`.
- `.github/workflows/pages.yml` — publica `dashboard.html` + el JSON cifrado
  a GitHub Pages cada vez que cambian.

## 🚀 Configuración inicial

### 1. Crea credenciales de Gmail API

1. Ve a [Google Cloud Console](https://console.cloud.google.com) → crea un proyecto.
2. Habilita la **Gmail API**.
3. Pantalla de consentimiento OAuth: tipo "Externo", estado "Testing", y
   agrégate a ti mismo como **Test user**.
4. Crea credenciales OAuth2 tipo **"Aplicación de escritorio"** y descarga el
   JSON como `credentials.json` en la raíz del proyecto (no lo subas a git).

### 2. Genera el token localmente (una sola vez)

```bash
pip install -r requirements.txt
python generate_token.py
```

Esto abre tu navegador para autorizar acceso de **solo lectura** a Gmail y
genera `token.json`. Al final imprime dos valores en base64.

### 3. Configura los Secrets y Variables en GitHub

En `Settings → Secrets and variables → Actions`:

**Secrets** (sensibles):
- `GMAIL_CREDENTIALS_B64` — valor impreso por `generate_token.py`
- `GMAIL_TOKEN_B64` — valor impreso por `generate_token.py`
- `DASHBOARD_PASSPHRASE` — una contraseña fuerte que tú eliges (ej. generada
  con `openssl rand -base64 24`). Úsala también al abrir el dashboard.

**Variables** (opcionales, tienen defaults en el código):
- `BANK_EMAIL` (default `notificaciones_bac@baccredomatic.sv,info@baccredomatic.com`, admite varios separados por coma)
- `BANK` (default `BAC`)
- `SYNC_DAYS` (default `30`)

Puedes hacerlo con `gh`:
```bash
gh secret set GMAIL_CREDENTIALS_B64 < credentials_b64.txt
gh secret set GMAIL_TOKEN_B64 < token_b64.txt
gh secret set DASHBOARD_PASSPHRASE -b "tu-passphrase-fuerte"
```

### 4. Habilita GitHub Pages

`Settings → Pages → Build and deployment → Source: GitHub Actions`.

### 5. Borra las credenciales locales

```bash
rm credentials.json token.json
```

Ya no las necesitas en tu máquina; viven como Secrets en GitHub.

## 📊 Dashboard interactivo

El dashboard filtra en vivo (fecha, tipo, comercio) sobre los datos ya
sincronizados, sin llamadas de red. El botón **"🔄 Buscar en Gmail"** además
dispara un sync real acotado al rango de fechas elegido, llamando a la API de
GitHub Actions directamente desde el navegador.

Para usarlo necesitas pegar, en el panel "⚙️ Configuración de sincronización"
del dashboard, un [Personal Access Token
fine-grained](https://github.com/settings/tokens?type=beta) limitado a este
repo con permisos **Actions: Read and write** y **Contents: Read**. El token
solo se guarda en `sessionStorage` de esa pestaña (nunca en el repo) y se
envía únicamente a `api.github.com`. Como el repo es público, no compartas
ese token ni lo pegues en otro sitio.

## 🔧 Ejecutar manualmente

Desde la pestaña **Actions** del repo, ejecuta el workflow `Sync Gmail
Expenses` con "Run workflow", o localmente:

```bash
pip install -r requirements.txt
CONFIG_DIR=. DASHBOARD_PASSPHRASE="tu-passphrase-fuerte" python gmail_reader.py
```

## 📝 Ajustar el parser de correos

Los patrones de extracción (monto, comercio, tarjeta) en `gmail_reader.py`
son genéricos — ajústalos (`AMOUNT_RE`, `MERCHANT_RE`, `CARD_RE`) al formato
real de los correos de notificación de tu banco.

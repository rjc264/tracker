# 💰 BAC Expense Tracker

Sincroniza automáticamente las notificaciones de transacciones bancarias (BAC)
desde Gmail hacia `data/expenses.json`, corriendo 100% en **GitHub Actions**
(no necesitas tener tu máquina encendida). Un dashboard estático se publica
en GitHub Pages para consultar los gastos desde cualquier lugar.

## ⚠️ Aviso de seguridad

Este repo es **privado**, pero **GitHub Pages publica el sitio con una URL
pública** (cualquiera con el link puede verlo, aunque el repo sea privado),
salvo que tengas GitHub Enterprise Cloud. Si prefieres que tus gastos no
sean accesibles públicamente, evita el workflow `pages.yml` y consulta
`data/expenses.json` directamente en el repo (`git pull`).

## 🏗️ Arquitectura

```
Gmail API ──(diario, cron)──> gmail_reader.py ──> data/expenses.json ──> commit
                                                          │
                                                          └──> GitHub Pages (dashboard.html)
```

- `.github/workflows/sync.yml` — corre diario (`workflow_dispatch` también),
  lee correos de `BANK_EMAIL`, actualiza `data/expenses.json` y hace commit.
- `.github/workflows/pages.yml` — publica `dashboard.html` + `data/expenses.json`
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

**Variables** (opcionales, tienen defaults en el código):
- `BANK_EMAIL` (default `notificaciones@bac.com.sv`)
- `BANK` (default `BAC`)
- `SYNC_DAYS` (default `30`)

Puedes hacerlo con `gh`:
```bash
gh secret set GMAIL_CREDENTIALS_B64 < credentials_b64.txt
gh secret set GMAIL_TOKEN_B64 < token_b64.txt
```

### 4. Habilita GitHub Pages

`Settings → Pages → Build and deployment → Source: GitHub Actions`.

### 5. Borra las credenciales locales

```bash
rm credentials.json token.json
```

Ya no las necesitas en tu máquina; viven como Secrets en GitHub.

## 🔧 Ejecutar manualmente

Desde la pestaña **Actions** del repo, ejecuta el workflow `Sync Gmail
Expenses` con "Run workflow", o localmente:

```bash
pip install -r requirements.txt
CONFIG_DIR=. python gmail_reader.py
```

## 📝 Ajustar el parser de correos

Los patrones de extracción (monto, comercio, tarjeta) en `gmail_reader.py`
son genéricos — ajústalos (`AMOUNT_RE`, `MERCHANT_RE`, `CARD_RE`) al formato
real de los correos de notificación de tu banco.

"""Sincroniza notificaciones bancarias de Gmail hacia data/expenses.json.

Pensado para correr sin intervención (GitHub Actions) usando un token OAuth
generado previamente con generate_token.py. Solo requiere el scope de lectura
gmail.readonly, nunca modifica ni borra correos.
"""
import base64
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from crypto_utils import decrypt_json, encrypt_json

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "."))
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
CREDENTIALS_FILE = CONFIG_DIR / os.environ.get("CREDENTIALS_FILE_NAME", "credentials.json")
TOKEN_FILE = CONFIG_DIR / os.environ.get("TOKEN_FILE_NAME", "token.json")
EXPENSES_FILE = DATA_DIR / "expenses.enc.json"

BANK_EMAIL = os.environ.get("BANK_EMAIL") or "notificaciones_bac@baccredomatic.sv,info@baccredomatic.com"
BANK_NAME = os.environ.get("BANK") or "BAC"
SYNC_DAYS = int(os.environ.get("SYNC_DAYS") or "30")
DASHBOARD_PASSPHRASE = os.environ.get("DASHBOARD_PASSPHRASE")
# Rango explícito (YYYY-MM-DD) para syncs bajo demanda desde el dashboard.
# Si no se definen, se usa la ventana de SYNC_DAYS hacia atrás desde hoy.
SYNC_SINCE = os.environ.get("SYNC_SINCE") or None
SYNC_UNTIL = os.environ.get("SYNC_UNTIL") or None

# NOTA: ajusta estos patrones al formato real de los correos de tu banco.
AMOUNT_RE = re.compile(r"(?:Monto|Amount)[:\s]*[A-Z]{0,3}\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
MERCHANT_RE = re.compile(r"(?:Comercio|Establecimiento|Merchant)[:\s]*(.+)", re.IGNORECASE)
CARD_RE = re.compile(r"(?:Tarjeta|Card)[^\d]{0,20}(\d{4})\b", re.IGNORECASE)

# Palabras clave para clasificar el movimiento por su origen.
CREDIT_CARD_RE = re.compile(r"tarjeta\s+de\s+cr[eé]dito|compra\s+con\s+tarjeta|autorizaci[oó]n", re.IGNORECASE)
DEBIT_CARD_RE = re.compile(r"tarjeta\s+de\s+d[eé]bito|compra\s+con\s+d[eé]bito", re.IGNORECASE)
TRANSFER_RE = re.compile(
    r"transferencia|transferiste|dep[oó]sito|abono\s+a\s+cuenta|env[ií]o\s+de\s+dinero", re.IGNORECASE
)


def detect_transaction_type(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    if CREDIT_CARD_RE.search(text):
        return "tarjeta_credito"
    if DEBIT_CARD_RE.search(text):
        return "tarjeta_debito"
    if TRANSFER_RE.search(text):
        return "transferencia"
    return "desconocido"


# Categorización por palabra clave sobre comercio + asunto + cuerpo del correo.
# Es heurística (no hay categoría real en la notificación del banco): ajusta
# las listas de palabras al vocabulario real de tus comercios frecuentes.
# El orden importa (se evalúa de arriba hacia abajo, gana la primera que matchee).
CATEGORY_PATTERNS = [
    ("salud", re.compile(
        r"farmaci|hospital|cl[ií]nica|laboratorio|dental|[oó]ptica|m[eé]dic|seguro\s+m[eé]dico",
        re.IGNORECASE,
    )),
    ("alimentacion", re.compile(
        r"super|despensa|walmart|pricesmart|la\s+colonia|restaurant|pizz|burger|mcdonald|"
        r"wendy|kfc|popeyes|pollo\s+campero|subway|starbucks|dunkin|caf[eé]|panader|"
        r"comida|food|delivery|pedidosya|rappi|uber\s*eats|didi\s*food",
        re.IGNORECASE,
    )),
    ("transporte", re.compile(
        r"uber(?!\s*eats)|cabify|indriver|didi(?!\s*food)|taxi|gasolina|gasolinera|combustible|"
        r"esso|texaco|puma\s+energy|shell|parqueo|parking|peaje|autob[uú]s\b",
        re.IGNORECASE,
    )),
    ("entretenimiento", re.compile(
        r"netflix|spotify|disney\+?|hbo|amazon\s*prime\s*video|youtube\s*premium|cinemark|"
        r"cinepolis|cine\b|steam|playstation|xbox|casino|discoteca|videojuego",
        re.IGNORECASE,
    )),
    ("viajes", re.compile(
        r"booking\.com|airbnb|despegar|avianca|volaris|copa\s+airlines|aeroline|hotel\b|hostal",
        re.IGNORECASE,
    )),
    ("servicios", re.compile(
        r"claro\b|tigo\b|movistar|digicel|cable\b|internet\b|electricidad|factura\s+de\s+luz|"
        r"agua\s+potable|\banda\b|del\s+sur|telefon[ií]a|plan\s+de\s+celular",
        re.IGNORECASE,
    )),
    ("vivienda", re.compile(
        r"alquiler|renta\s+de\s+casa|hipoteca|ferreter|condominio|mantenimiento\s+del?\s+hogar",
        re.IGNORECASE,
    )),
    ("compras", re.compile(
        r"amazon(?!\s*prime\s*video)|ebay|aliexpress|siman\b|la\s+curacao|shein|mall\b|"
        r"tienda\b|zara\b|best\s+buy",
        re.IGNORECASE,
    )),
]


def detect_category(merchant: str, subject: str, body: str = "") -> str:
    text = f"{merchant or ''}\n{subject or ''}\n{body or ''}"
    for category, pattern in CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "otros"


def execute_with_retry(request, max_retries: int = 6):
    """Ejecuta una request de la API de Gmail reintentando con backoff
    exponencial cuando se excede la cuota (403/429 rateLimitExceeded)."""
    for attempt in range(max_retries):
        try:
            return request.execute()
        except HttpError as exc:
            status = exc.resp.status if exc.resp is not None else None
            is_rate_limit = status in (403, 429) and "rateLimitExceeded" in str(exc)
            if not is_rate_limit or attempt == max_retries - 1:
                raise
            wait = min(2 ** attempt, 60)
            print(f"⚠️  Límite de cuota de Gmail alcanzado, reintentando en {wait}s...")
            time.sleep(wait)


def get_credentials() -> Credentials:
    if not TOKEN_FILE.exists():
        raise SystemExit(
            f"No se encontró {TOKEN_FILE}. Genera uno localmente con generate_token.py "
            "y guárdalo como GitHub Secret (ver README.md)."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def extract_text(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        text = extract_text(part)
        if text:
            return text
    return ""


def parse_transaction(subject: str, body: str, msg_id: str, internal_date: str) -> Optional[dict]:
    amount_match = AMOUNT_RE.search(body) or AMOUNT_RE.search(subject)
    if not amount_match:
        return None
    merchant_match = MERCHANT_RE.search(body)
    card_match = CARD_RE.search(body)
    merchant = merchant_match.group(1).strip() if merchant_match else subject
    return {
        "id": msg_id,
        "date": datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat(),
        "amount": float(amount_match.group(1).replace(",", "")),
        "merchant": merchant,
        "card_last4": card_match.group(1) if card_match else None,
        "type": detect_transaction_type(subject, body),
        "category": detect_category(merchant, subject, body),
        "bank": BANK_NAME,
        "subject": subject,
    }


def load_existing() -> dict:
    if EXPENSES_FILE.exists():
        envelope = json.loads(EXPENSES_FILE.read_text(encoding="utf-8"))
        return decrypt_json(envelope, DASHBOARD_PASSPHRASE)
    return {"expenses": []}


def main() -> None:
    if not DASHBOARD_PASSPHRASE:
        raise SystemExit(
            "Falta la variable de entorno DASHBOARD_PASSPHRASE (guárdala como GitHub Secret)."
        )
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    if SYNC_SINCE:
        after = datetime.strptime(SYNC_SINCE, "%Y-%m-%d").strftime("%Y/%m/%d")
    else:
        after = (datetime.now(timezone.utc) - timedelta(days=SYNC_DAYS)).strftime("%Y/%m/%d")

    senders = [s.strip() for s in BANK_EMAIL.split(",") if s.strip()]
    from_clause = " OR ".join(f"from:{s}" for s in senders)
    query = f"({from_clause}) after:{after}"

    if SYNC_UNTIL:
        # Gmail excluye el día de "before:", se suma 1 día para incluir SYNC_UNTIL completo.
        before = (datetime.strptime(SYNC_UNTIL, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y/%m/%d")
        query += f" before:{before}"

    data = load_existing()
    known_ids = {e["id"] for e in data["expenses"]}
    new_count = 0

    request = service.users().messages().list(userId="me", q=query)
    while request is not None:
        response = execute_with_retry(request)
        for msg_ref in response.get("messages", []):
            if msg_ref["id"] in known_ids:
                continue
            msg = execute_with_retry(
                service.users().messages().get(userId="me", id=msg_ref["id"], format="full")
            )
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            body = extract_text(msg["payload"])
            transaction = parse_transaction(headers.get("Subject", ""), body, msg_ref["id"], msg["internalDate"])
            if transaction:
                data["expenses"].append(transaction)
                known_ids.add(msg_ref["id"])
                new_count += 1
            time.sleep(0.2)
        request = service.users().messages().list_next(request, response)

    # Recategoriza todas las transacciones (no solo las nuevas) por si
    # CATEGORY_PATTERNS cambió desde el último sync. Usa merchant/subject
    # ya guardados, porque el cuerpo del correo no se persiste.
    for expense in data["expenses"]:
        expense["category"] = detect_category(expense.get("merchant", ""), expense.get("subject", ""))

    data["expenses"].sort(key=lambda e: e["date"], reverse=True)
    data["last_sync"] = datetime.now(timezone.utc).isoformat()

    envelope = encrypt_json(data, DASHBOARD_PASSPHRASE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPENSES_FILE.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    print(f"✅ Sincronizado. {new_count} transacciones nuevas. Total: {len(data['expenses'])}")


if __name__ == "__main__":
    main()

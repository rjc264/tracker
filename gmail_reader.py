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

# Formato real confirmado del correo "Alerta PRF BAC Credomatic" (texto plano,
# linealizado desde una tabla HTML): las etiquetas aparecen antes que sus
# valores, cada una en su propia línea. Ej.:
#   Comercio\n\nMonto\n\nSELECTOS MASFERRER\n\n7.67
#   Fecha y hora\n\n2026/09/12-21:40:01
#   Tipo de la compra\n\nEstado\n\nTarjeta Presente\n\nAprobada
# Este correo NUNCA dice si la tarjeta es de crédito o débito (solo la marca
# y los últimos 4 dígitos) — ver CARD_TYPE_MAP más abajo.
TABLE_MERCHANT_AMOUNT_RE = re.compile(
    r"Comercio\s*\n+\s*Monto\s*\n+\s*(?P<merchant>.+?)\s*\n+\s*(?P<amount>[\d,]+\.\d{2})",
    re.IGNORECASE,
)
TABLE_STATUS_RE = re.compile(
    r"Tipo\s+de\s+la\s+compra\s*\n+\s*Estado\s*\n+\s*(?P<presence>.+?)\s*\n+\s*(?P<status>.+?)\s*\n",
    re.IGNORECASE,
)
CARD_LAST4_RE = re.compile(r"tarjeta\s+\S+\s+terminada\s+en\s+(\d{4})", re.IGNORECASE)
APPROVED_RE = re.compile(r"aprob", re.IGNORECASE)

# Fallback genérico ("Comercio: X", "Monto: $X") por si otro tipo de correo de
# BAC (ej. transferencias) usa un formato distinto al de la tabla de arriba.
AMOUNT_RE = re.compile(r"(?:Monto|Amount)[:\s]*[A-Z]{0,3}\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
MERCHANT_RE = re.compile(r"(?:Comercio|Establecimiento|Merchant)[:\s]*(.+)", re.IGNORECASE)
CARD_RE = re.compile(r"(?:Tarjeta|Card)[^\d]{0,20}(\d{4})\b", re.IGNORECASE)

# Palabras clave para clasificar el movimiento por su origen. El correo real
# no distingue crédito de débito, así que primero se intenta CARD_TYPE_MAP.
CREDIT_CARD_RE = re.compile(r"tarjeta\s+de\s+cr[eé]dito|autorizaci[oó]n", re.IGNORECASE)
DEBIT_CARD_RE = re.compile(r"tarjeta\s+de\s+d[eé]bito", re.IGNORECASE)
TRANSFER_RE = re.compile(
    r"transferencia|transferiste|dep[oó]sito|abono\s+a\s+cuenta|env[ií]o\s+de\s+dinero", re.IGNORECASE
)

# Mapa opcional "ultimos4:tipo,ultimos4:tipo" (ej. "8825:tarjeta_credito,
# 4321:tarjeta_debito") para GitHub Variable CARD_TYPE_MAP. El correo del
# banco nunca dice si una tarjeta es de crédito o débito — solo tú lo sabes.
CARD_TYPE_MAP = {}
for _pair in (os.environ.get("CARD_TYPE_MAP") or "").split(","):
    if ":" in _pair:
        _last4, _kind = _pair.split(":", 1)
        CARD_TYPE_MAP[_last4.strip()] = _kind.strip()


def detect_transaction_type(subject: str, body: str, card_last4: Optional[str] = None) -> str:
    if card_last4 and card_last4 in CARD_TYPE_MAP:
        return CARD_TYPE_MAP[card_last4]
    text = f"{subject}\n{body}"
    if CREDIT_CARD_RE.search(text):
        return "tarjeta_credito"
    if DEBIT_CARD_RE.search(text):
        return "tarjeta_debito"
    if TRANSFER_RE.search(text):
        return "transferencia"
    if card_last4:
        # Sabemos que es una compra con tarjeta, pero no si es crédito o
        # débito (el correo no lo dice y no está en CARD_TYPE_MAP).
        return "tarjeta"
    return "desconocido"


# Taxonomía de categorización tomada de Clasificacion_Comercios_El_Salvador.xlsx
# (hoja "Taxonomía": 13 categorías / 41 subcategorías, con ejemplos reales de
# comercios de El Salvador; hoja "Reglas": normalizar el comercio quitando
# prefijos de procesador antes de clasificar, priorizar el comercio sobre el
# procesador, y usar reglas conocidas antes que heurísticas genéricas).
# Claves ascii en minúscula (sin tildes) para que coincidan con
# categoryLabels/categoryColors en dashboard.html — si agregas una categoría o
# subcategoría nueva aquí, agrégala también ahí.

# Prefijos de procesador de pago a quitar del comercio mostrado (Reglas #1).
# Puede haber más de uno encadenado (ej. "DLOCAL* DLC TEMU").
_PROCESSOR_PREFIX_RE = re.compile(r"^\s*(WOMPI|DLOCAL|DLC|PAYPAL)[\*\s]+", re.IGNORECASE)


def normalize_merchant(raw: str) -> str:
    text = (raw or "").strip()
    previous = None
    while previous != text:
        previous = text
        text = _PROCESSOR_PREFIX_RE.sub("", text).strip()
    return text or (raw or "").strip()


# Reglas de marca conocidas (hoja "Ejemplos"): más específicas y confiables
# que la taxonomía genérica, así que se evalúan primero (Reglas #3).
# (regex, nombre normalizado, categoría, subcategoría)
BRAND_RULES = [
    (r"pizza\s*hut", "Pizza Hut", "alimentacion", "comida_rapida"),
    (r"kako.?s?\s*gastrobar", "Kakos Gastrobar", "alimentacion", "bares_gastrobares"),
    (r"starbucks", "Starbucks", "alimentacion", "cafeterias"),
    (r"pedidosya", "PedidosYa", "alimentacion", "delivery"),
    (r"uber\s*eats", "Uber Eats", "alimentacion", "delivery"),
    (r"\buber\b", "Uber", "transporte", "uber_taxi"),
    (r"texaco", "Texaco", "transporte", "combustible"),
    (r"\btemu\b", "Temu", "compras", "marketplace"),
    (r"telef[oó]nica", "Telefónica", "hogar_servicios", "telefonia_movil"),
    (r"\bselectos\b|super\s*selectos", "Selectos", "alimentacion", "supermercado"),
    (r"siteground", "SiteGround", "tecnologia_software", "hosting"),
    (r"anthropic|\bclaude\b", "Claude", "tecnologia_software", "saas"),
    (r"apple\.com|apple\s*store", "Apple", "tecnologia_software", "apps_software"),
    (r"\banda\b", "ANDA", "hogar_servicios", "agua"),
    (r"disney\+?", "Disney+", "entretenimiento", "streaming"),
    (r"transfer\s*365", "Transfer365", "finanzas", "transferencias"),
]
BRAND_RULES = [
    (re.compile(pattern, re.IGNORECASE), name, category, subcategory)
    for pattern, name, category, subcategory in BRAND_RULES
]

# Taxonomía general por palabra clave (hoja "Taxonomía"), en el mismo orden
# que la hoja de cálculo. Es heurística: ajusta las listas al vocabulario
# real de tus comercios frecuentes si algo cae en "otros/sin_identificar".
CATEGORY_TAXONOMY = [
    ("alimentacion", "supermercado", r"walmart|despensa\s+de\s+don\s+juan|pricesmart|la\s+colonia|super(?!visor)"),
    ("alimentacion", "restaurantes", r"\bkoi\b|casa\s+parrillada|restaurant"),
    ("alimentacion", "comida_rapida", r"subway|mcdonald|burger\s+king|mister\s+donut|wendy|kfc|popeyes|pollo\s+campero"),
    ("alimentacion", "cafeterias", r"kind\s+coffee|cafeter[ií]a|\bcaf[eé]\b"),
    ("alimentacion", "panaderia", r"panader[ií]a"),
    ("alimentacion", "delivery", r"\bhugo\b|rappi|didi\s*food"),
    ("alimentacion", "bares_gastrobares", r"\bcadejo\b|beer\s+station|gastrobar|\bbar\b"),
    ("transporte", "combustible", r"\bshell\b|\bpuma\b|gasolinera|gasolina|combustible|esso"),
    ("transporte", "uber_taxi", r"cabify|indriver|\btaxi\b"),
    ("transporte", "parqueos", r"tuscania\s+parqueos|parqueo|estacionamiento|paystation|\bparking\b"),
    ("compras", "ropa", r"stradivarius|tienda\s+de\s+ropa|\bzara\b"),
    ("compras", "hogar", r"casa\s+depot|mucha\s+casa|ferreter"),
    ("compras", "departamentales", r"almacenes\s+siman|\bsiman\b"),
    ("compras", "tecnologia", r"zona\s+digital"),
    ("compras", "marketplace", r"marketplace|\bamazon\b(?!\s*prime\s*video)|\bebay\b|aliexpress|\bshein\b"),
    ("salud", "farmacia", r"farmaci"),
    ("salud", "medico_clinicas", r"cl[ií]nica|m[eé]dic|hospital"),
    ("salud", "dental", r"dental|dentista"),
    ("salud", "optica", r"[oó]ptica"),
    ("cuidado_personal", "belleza", r"sal[oó]n\s+de\s+belleza|barber|\bspa\b"),
    ("cuidado_personal", "cosmeticos", r"belcorp|cosm[eé]tic"),
    ("cuidado_personal", "flores_regalos", r"floreria|florister[ií]a|regalos"),
    ("hogar_servicios", "agua", r"agua\s+potable"),
    ("hogar_servicios", "electricidad", r"\bcaess\b|delsur|del\s+sur|electricidad|distribuidora\s+el[eé]ctrica"),
    ("hogar_servicios", "telefonia_movil", r"\btigo\b|\bclaro\b|movistar|digicel|plan\s+de\s+celular"),
    ("hogar_servicios", "internet", r"proveedor(?:es)?\s+de\s+internet|\binternet\b"),
    ("tecnologia_software", "saas", r"\bgithub\b|\bsaas\b"),
    ("tecnologia_software", "hosting", r"\bhosting\b"),
    ("tecnologia_software", "apps_software", r"\bgoogle\b|\bmicrosoft\b|\bsoftware\b"),
    ("viajes", "hoteles", r"beach\s+break\s+hotel|i32\s+hotel|\bhotel\b|\bhostal\b"),
    ("viajes", "vuelos", r"avianca|volaris|copa\s+airlines|aerol[ií]nea"),
    ("viajes", "transporte_internacional", r"agencia\s+de\s+viajes"),
    ("entretenimiento", "streaming", r"netflix|\bmax\b|spotify"),
    ("entretenimiento", "eventos", r"concierto|\bevento\b"),
    ("entretenimiento", "deportes", r"gimnasio|\bgym\b"),
    ("finanzas", "transferencias", r"transferencia"),
    ("finanzas", "comisiones", r"comisi[oó]n\s+bancaria|cargo\s+financiero"),
    ("finanzas", "pagos_financieros", r"pr[eé]stamo|pago\s+de\s+tarjeta"),
    ("educacion", "educacion", r"colegio|universidad|\bcurso\b"),
    ("gobierno", "gobierno", r"alcald[ií]a|institucion\s+gubernamental"),
    ("otros", "donaciones", r"donaci[oó]n"),
]
CATEGORY_TAXONOMY = [
    (category, subcategory, re.compile(pattern, re.IGNORECASE))
    for category, subcategory, pattern in CATEGORY_TAXONOMY
]


def detect_category(merchant: str, subject: str, body: str = ""):
    """Devuelve (categoria, subcategoria) usando primero BRAND_RULES (marcas
    conocidas y confirmadas) y luego la taxonomía genérica por palabra clave.
    """
    text = f"{merchant or ''}\n{subject or ''}\n{body or ''}"
    for pattern, _name, category, subcategory in BRAND_RULES:
        if pattern.search(text):
            return category, subcategory
    for category, subcategory, pattern in CATEGORY_TAXONOMY:
        if pattern.search(text):
            return category, subcategory
    return "otros", "sin_identificar"


def brand_display_name(merchant: str, subject: str, body: str = "") -> Optional[str]:
    """Nombre de comercio normalizado si coincide con una marca conocida
    (Reglas #2: priorizar el comercio real sobre el procesador de pago)."""
    text = f"{merchant or ''}\n{subject or ''}\n{body or ''}"
    for pattern, name, _category, _subcategory in BRAND_RULES:
        if pattern.search(text):
            return name
    return None


# Correos de "abono a su cuenta" / detalle de crédito son ingresos, no gasto.
INCOME_BODY_RE = re.compile(r"ha\s+recibido\s+un\s+abono\s+a\s+su\s+cuenta", re.IGNORECASE)
INCOME_SUBJECT_RE = re.compile(r"detalle\s+de\s+cr[eé]dito", re.IGNORECASE)


def detect_direction(subject: str, body: str = "") -> str:
    if INCOME_SUBJECT_RE.search(subject or "") or INCOME_BODY_RE.search(body or ""):
        return "ingreso"
    return "gasto"


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
    table_match = TABLE_MERCHANT_AMOUNT_RE.search(body)
    if table_match:
        merchant = table_match.group("merchant").strip()
        amount = float(table_match.group("amount").replace(",", ""))
    else:
        # Fallback para formatos que no sean la tabla "Comercio/Monto".
        amount_match = AMOUNT_RE.search(body) or AMOUNT_RE.search(subject)
        if not amount_match:
            return None
        merchant_match = MERCHANT_RE.search(body)
        merchant = merchant_match.group(1).strip() if merchant_match else subject
        amount = float(amount_match.group(1).replace(",", ""))

    status_match = TABLE_STATUS_RE.search(body)
    card_present = None
    if status_match:
        if not APPROVED_RE.search(status_match.group("status")):
            # Transacción rechazada/declinada: no es un gasto real.
            return None
        card_present = "no presente" not in status_match.group("presence").lower()

    card_match = CARD_LAST4_RE.search(body) or CARD_RE.search(body)
    card_last4 = card_match.group(1) if card_match else None

    merchant = brand_display_name(merchant, subject, body) or normalize_merchant(merchant)
    category, subcategory = detect_category(merchant, subject, body)

    return {
        "id": msg_id,
        "date": datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat(),
        "amount": amount,
        "merchant": merchant,
        "card_last4": card_last4,
        "card_present": card_present,
        "type": detect_transaction_type(subject, body, card_last4),
        "category": category,
        "subcategory": subcategory,
        "direction": detect_direction(subject, body),
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

    # Reclasifica todas las transacciones (no solo las nuevas) por si
    # CATEGORY_TAXONOMY/BRAND_RULES/CARD_TYPE_MAP cambiaron desde el último
    # sync. Usa merchant/subject/card_last4 ya guardados, porque el cuerpo
    # del correo no se persiste — por eso detect_direction solo puede
    # reevaluar la señal del asunto ("detalle de crédito"), no la del cuerpo
    # ("...ha recibido un abono...") para transacciones ya sincronizadas.
    for expense in data["expenses"]:
        merchant = expense.get("merchant", "")
        subject = expense.get("subject", "")
        category, subcategory = detect_category(merchant, subject)
        expense["category"] = category
        expense["subcategory"] = subcategory
        expense["type"] = detect_transaction_type(subject, "", expense.get("card_last4"))
        expense["direction"] = expense.get("direction") or detect_direction(subject)

    data["expenses"].sort(key=lambda e: e["date"], reverse=True)
    data["last_sync"] = datetime.now(timezone.utc).isoformat()

    envelope = encrypt_json(data, DASHBOARD_PASSPHRASE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPENSES_FILE.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    print(f"✅ Sincronizado. {new_count} transacciones nuevas. Total: {len(data['expenses'])}")


if __name__ == "__main__":
    main()

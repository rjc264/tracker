"""Sincroniza notificaciones bancarias de Gmail hacia data/expenses.json.

Pensado para correr sin intervención (GitHub Actions) usando un token OAuth
generado previamente con generate_token.py. Solo requiere el scope de lectura
gmail.readonly, nunca modifica ni borra correos.
"""
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "."))
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
CREDENTIALS_FILE = CONFIG_DIR / os.environ.get("CREDENTIALS_FILE_NAME", "credentials.json")
TOKEN_FILE = CONFIG_DIR / os.environ.get("TOKEN_FILE_NAME", "token.json")
EXPENSES_FILE = DATA_DIR / "expenses.json"

BANK_EMAIL = os.environ.get("BANK_EMAIL", "notificaciones@bac.com.sv")
BANK_NAME = os.environ.get("BANK", "BAC")
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "30"))

# NOTA: ajusta estos patrones al formato real de los correos de tu banco.
AMOUNT_RE = re.compile(r"(?:Monto|Amount)[:\s]*[A-Z]{0,3}\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
MERCHANT_RE = re.compile(r"(?:Comercio|Establecimiento|Merchant)[:\s]*(.+)", re.IGNORECASE)
CARD_RE = re.compile(r"(?:Tarjeta|Card)[^\d]{0,20}(\d{4})\b", re.IGNORECASE)


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
    return {
        "id": msg_id,
        "date": datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat(),
        "amount": float(amount_match.group(1).replace(",", "")),
        "merchant": merchant_match.group(1).strip() if merchant_match else subject,
        "card_last4": card_match.group(1) if card_match else None,
        "bank": BANK_NAME,
        "subject": subject,
    }


def load_existing() -> dict:
    if EXPENSES_FILE.exists():
        return json.loads(EXPENSES_FILE.read_text(encoding="utf-8"))
    return {"expenses": []}


def main() -> None:
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    after = (datetime.now(timezone.utc) - timedelta(days=SYNC_DAYS)).strftime("%Y/%m/%d")
    query = f"from:{BANK_EMAIL} after:{after}"

    data = load_existing()
    known_ids = {e["id"] for e in data["expenses"]}
    new_count = 0

    request = service.users().messages().list(userId="me", q=query)
    while request is not None:
        response = request.execute()
        for msg_ref in response.get("messages", []):
            if msg_ref["id"] in known_ids:
                continue
            msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            body = extract_text(msg["payload"])
            transaction = parse_transaction(headers.get("Subject", ""), body, msg_ref["id"], msg["internalDate"])
            if transaction:
                data["expenses"].append(transaction)
                known_ids.add(msg_ref["id"])
                new_count += 1
        request = service.users().messages().list_next(request, response)

    data["expenses"].sort(key=lambda e: e["date"], reverse=True)
    data["last_sync"] = datetime.now(timezone.utc).isoformat()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPENSES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Sincronizado. {new_count} transacciones nuevas. Total: {len(data['expenses'])}")


if __name__ == "__main__":
    main()

"""Genera token.json para acceso a Gmail. Ejecutar UNA VEZ, en tu máquina local (nunca en CI).

Requisitos previos:
  1. Crea un proyecto en https://console.cloud.google.com y habilita la Gmail API.
  2. Crea credenciales OAuth2 de tipo "Aplicación de escritorio" y descárgalas como credentials.json.
  3. Coloca credentials.json en la raíz de este proyecto.

Este script abre el navegador para autorizar acceso de solo lectura a Gmail y
guarda token.json. Luego imprime ambos archivos en base64 para copiarlos como
GitHub Secrets (GMAIL_CREDENTIALS_B64 y GMAIL_TOKEN_B64) — nunca los subas al repo.
"""
import base64
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = os.environ.get("CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.environ.get("TOKEN_FILE", "token.json")


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"\n✅ Token guardado en {TOKEN_FILE}\n")

    print("Copia estos valores en GitHub → Settings → Secrets and variables → Actions:\n")
    for secret_name, path in (
        ("GMAIL_CREDENTIALS_B64", CREDENTIALS_FILE),
        ("GMAIL_TOKEN_B64", TOKEN_FILE),
    ):
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        print(f"--- {secret_name} ---")
        print(encoded)
        print()


if __name__ == "__main__":
    main()

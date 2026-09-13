"""Cifrado AES-GCM con clave derivada por PBKDF2 a partir de una passphrase.

El mismo esquema se replica en el navegador con la Web Crypto API
(ver dashboard.html), para que lo cifrado aquí pueda descifrarse ahí.
El "envelope" resultante (salt, iv, iteraciones, ciphertext) no es secreto:
solo la passphrase lo es.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Recomendación OWASP para PBKDF2-HMAC-SHA256 (2023): >= 600k idealmente;
# se usa un valor menor para mantener el desciframiento ágil en el navegador.
PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16
IV_BYTES = 12


def _derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_json(data: dict, passphrase: str) -> dict:
    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)
    key = _derive_key(passphrase, salt, PBKDF2_ITERATIONS)
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "iterations": PBKDF2_ITERATIONS,
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def decrypt_json(envelope: dict, passphrase: str) -> dict:
    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    iterations = envelope.get("iterations", PBKDF2_ITERATIONS)
    key = _derive_key(passphrase, salt, iterations)
    ciphertext = base64.b64decode(envelope["ciphertext"])
    plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))

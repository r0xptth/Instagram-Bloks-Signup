"""Instagram #PWD_BROWSER password encryption."""

from __future__ import annotations

import base64
import os
import struct
import time


def encrypt_password_browser(
    password: str, pub_key_hex: str, key_id: int, version: str = "10"
) -> str:
    """
    Produce Instagram's ``#PWD_BROWSER:<version>:<time>:<b64>`` enc_password.

    AES-256-GCM + libsodium sealed box — same scheme as desktop Chrome / mobile web.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from nacl.public import PublicKey, SealedBox

    timestamp = str(int(time.time()))
    aes_key = os.urandom(32)
    iv = bytes(12)
    ct = AESGCM(aes_key).encrypt(
        iv, password.encode("utf-8"), timestamp.encode("utf-8")
    )
    ciphertext, tag = ct[:-16], ct[-16:]
    sealed = SealedBox(PublicKey(bytes.fromhex(pub_key_hex))).encrypt(aes_key)
    payload = (
        struct.pack("<BBH", 1, int(key_id), len(sealed)) + sealed + tag + ciphertext
    )
    return f"#PWD_BROWSER:{version}:{timestamp}:" + base64.b64encode(payload).decode()

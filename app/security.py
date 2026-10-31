"""Authentication helpers: PBKDF2 password hashing and HS256 JWT (stdlib only)."""
import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me").encode()
ROLES = {"commander", "operator", "crew", "admin"}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{_b64(salt)}${_b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    salt_b64, _ = stored.split("$")
    return hmac.compare_digest(hash_password(password, _unb64(salt_b64)), stored)


def create_token(user_id: str, role: str, ttl: int = 8 * 3600) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": user_id, "role": role, "exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(SECRET, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode_token(token: str) -> dict | None:
    """Return the claims if the signature is valid and the token has not expired."""
    try:
        header, body, sig = token.split(".")
        expected = _b64(hmac.new(SECRET, f"{header}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_unb64(body))
        return claims if claims["exp"] >= time.time() else None
    except Exception:
        return None

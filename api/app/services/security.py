"""Security helpers: PAN hashing and password hashing.

IMPORTANT (PRD constraint): the PAN is NEVER stored in clear — only an
irreversible salted hash is kept and used for matching.
"""

import hashlib
import hmac

import bcrypt

from ..config import settings


def hash_pan(pan: str) -> str:
    """Irreversible, keyed hash of a PAN (HMAC-SHA256 with a server secret).

    Using HMAC with a secret salt means the stored value cannot be reversed
    and cannot be brute-forced without the secret. NOTE: the hashing/salt
    strategy must be validated with the bank's security team before production.
    """
    if settings.pan_hash_secret in ("", "change-me-in-env"):
        raise ValueError("Configure PAN_HASH_SECRET before hashing cards")
    return hmac.new(
        settings.pan_hash_secret.encode("utf-8"),
        pan.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > 72:
        raise ValueError("Password exceeds 72 UTF-8 bytes")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")
    if len(pw) > 72:
        return False
    return bcrypt.checkpw(pw, password_hash.encode("utf-8"))

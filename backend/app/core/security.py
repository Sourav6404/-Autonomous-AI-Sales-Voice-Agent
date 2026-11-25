"""Security, cryptography, password hashing, and JWT token management."""

import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set
import jwt
from backend.app.core.config import settings
from backend.app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class TokenBlacklist:
    """Thread-safe in-memory token blacklist for session invalidation/logout,
    with an extensible design for distributed storage (e.g., Redis).
    """

    _revoked_tokens: Dict[str, float] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def revoke(cls, token: str, expires_at_timestamp: float) -> None:
        """Revokes a token until its natural expiration timestamp."""
        with cls._lock:
            cls._clean_expired_locked()
            cls._revoked_tokens[token] = expires_at_timestamp

    @classmethod
    def revoke_token(cls, token: str, expires_at: Optional[float] = None) -> None:
        """Revokes a token, automatically deriving expiration timestamp from JWT payload."""
        if expires_at is None:
            decoded = decode_token(token, check_blacklist=False)
            if decoded and "exp" in decoded:
                expires_at = float(decoded["exp"])
            else:
                expires_at = time.time() + 86400.0
        cls.revoke(token, expires_at)

    @classmethod
    def is_revoked(cls, token: str) -> bool:
        """Checks if a token has been explicitly revoked."""
        with cls._lock:
            cls._clean_expired_locked()
            return token in cls._revoked_tokens

    @classmethod
    def _clean_expired_locked(cls) -> None:
        """Removes expired entries from blacklist. Assumes caller holds _lock."""
        now = time.time()
        expired = [t for t, exp in cls._revoked_tokens.items() if exp < now]
        for t in expired:
            del cls._revoked_tokens[t]


class RedisTokenBlacklist:
    """Production Redis-backed distributed token blacklist interface.

    In production multi-worker environments, sets key `bl:<token>` with TTL = token exp - now.
    Falls back gracefully to in-memory TokenBlacklist if Redis is unavailable or unconfigured.
    """

    _redis_client = None

    @classmethod
    def get_redis(cls):
        if cls._redis_client is None:
            redis_url = getattr(settings, "REDIS_URL", None)
            if redis_url:
                try:
                    import redis
                    cls._redis_client = redis.from_url(redis_url, decode_responses=True)
                except Exception as e:
                    logger.warning("Redis unavailable for distributed blacklist: %s", e)
        return cls._redis_client

    @classmethod
    def revoke_token(cls, token: str, expires_at: Optional[float] = None) -> None:
        r = cls.get_redis()
        if r:
            try:
                if expires_at is None:
                    decoded = decode_token(token, check_blacklist=False)
                    expires_at = float(decoded["exp"]) if decoded and "exp" in decoded else time.time() + 86400.0
                ttl = max(1, int(expires_at - time.time()))
                r.setex(f"bl:{token}", ttl, "1")
                return
            except Exception as e:
                logger.error("Failed to write to Redis token blacklist: %s", e)
        # Fallback to in-memory blacklist
        TokenBlacklist.revoke_token(token, expires_at)

    @classmethod
    def is_revoked(cls, token: str) -> bool:
        r = cls.get_redis()
        if r:
            try:
                return r.exists(f"bl:{token}") > 0
            except Exception as e:
                logger.error("Failed to check Redis token blacklist: %s", e)
        # Fallback to in-memory blacklist
        return TokenBlacklist.is_revoked(token)


class PasswordHasher:
    """Cryptographically secure password hashing using Scrypt (RFC 7914)."""

    N: int = 16384
    R: int = 8
    P: int = 1

    @classmethod
    def hash(cls, password: str) -> str:
        """Hashes a password with a fresh random 16-byte salt."""
        salt = os.urandom(16)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=cls.N,
            r=cls.R,
            p=cls.P,
        )
        return f"$scrypt$n={cls.N},r={cls.R},p={cls.P}${salt.hex()}${derived.hex()}"

    @classmethod
    def verify(cls, password: str, hashed: str) -> bool:
        """Verifies a password against an existing scrypt hash in constant time."""
        try:
            parts = hashed.split("$")
            if len(parts) != 5 or parts[1] != "scrypt":
                return False
            # Parse parameters: n=16384,r=8,p=1
            params = dict(kv.split("=") for kv in parts[2].split(","))
            n = int(params["n"])
            r = int(params["r"])
            p = int(params["p"])
            salt = bytes.fromhex(parts[3])
            expected = bytes.fromhex(parts[4])

            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
            )
            return hmac.compare_digest(derived, expected)
        except Exception:
            return False


def hash_password(password: str) -> str:
    """Convenience helper to hash a password."""
    return PasswordHasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Convenience helper to verify a password."""
    return PasswordHasher.verify(password, hashed_password)


def create_access_token(
    subject: str,
    org_id: str,
    role: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Generates a signed JWT access token containing subject, org_id, and role claims."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "org_id": str(org_id),
        "role": str(role),
        "email": str(email),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def create_refresh_token(subject: str, org_id: str) -> str:
    """Generates a long-lived signed JWT refresh token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "org_id": str(org_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str, check_blacklist: bool = True) -> Dict[str, Any]:
    """Decodes and validates a JWT token, ensuring it has not expired or been revoked."""
    if check_blacklist and RedisTokenBlacklist.is_revoked(token):
        raise AppException(
            message="Token has been revoked or logged out.",
            code="TOKEN_REVOKED",
            status_code=401,
        )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AppException(
            message="Authentication token has expired.",
            code="TOKEN_EXPIRED",
            status_code=401,
        )
    except jwt.InvalidTokenError:
        raise AppException(
            message="Invalid authentication token.",
            code="TOKEN_INVALID",
            status_code=401,
        )

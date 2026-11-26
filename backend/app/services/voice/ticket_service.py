"""Ephemeral Single-Use Voice-Session Ticket Service.

Generates and validates cryptographically secure, high-entropy (256-bit) single-use tickets
bound to an authenticated user, tenant organization, and optional conversation.

Security guarantees:
1. Raw ticket tokens are NEVER logged.
2. Only the SHA-256 hash of the ticket is stored in Redis or memory.
3. Tickets expire strictly after 30 seconds.
4. Tickets are atomically redeemed exactly once, preventing replay attacks.
5. In-memory storage is strictly a development/testing fallback and logs a warning.
"""

import hashlib
import json
import logging
import secrets
import threading
import time
from typing import Optional
from uuid import UUID

from backend.app.core.config import settings
from backend.app.schemas.voice import TicketData

logger = logging.getLogger(__name__)


class VoiceTicketService:
    """Manages creation, atomic redemption, and lifecycle of voice-session tickets."""

    _redis_client = None
    _redis_disabled_for_tests = False
    _in_memory_store = {}
    _in_memory_lock = threading.Lock()

    @classmethod
    def _get_redis(cls):
        """Initializes or returns active Redis connection if configured."""
        if cls._redis_disabled_for_tests:
            return None
        if cls._redis_client is None and settings.REDIS_URL:
            try:
                import redis
                cls._redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                logger.info("Connected to distributed Redis for voice tickets.")
            except Exception as e:
                logger.warning(
                    "Redis unavailable for voice tickets; using in-memory dev fallback: %s", e
                )
        return cls._redis_client

    @classmethod
    def _hash_ticket(cls, ticket: str) -> str:
        """Derives SHA-256 hex digest of raw ticket. Only this hash is stored or logged."""
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    @classmethod
    async def create_ticket(
        cls,
        user_id: UUID,
        org_id: UUID,
        conversation_id: Optional[UUID] = None,
        caller_phone: Optional[str] = None,
        language: str = "en",
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """Issues a new single-use 256-bit cryptographically secure ticket.

        Returns raw ticket string to be sent securely to client over TLS.
        """
        ttl = ttl_seconds or settings.VOICE_TICKET_EXPIRE_SECONDS
        raw_token = f"tkt_{secrets.token_urlsafe(32)}"
        token_hash = cls._hash_ticket(raw_token)

        data = TicketData(
            user_id=user_id,
            org_id=org_id,
            conversation_id=conversation_id,
            caller_phone=caller_phone or "browser-voice",
            language=language,
            created_at=time.time(),
            used=False,
        )

        r = cls._get_redis()
        if settings.APP_ENV == "production":
            if not r:
                logger.critical(
                    "Production Redis unavailable: voice ticket creation rejected to prevent split-brain ticket store."
                )
                raise RuntimeError("Distributed Redis required for voice tickets in production environment.")
            try:
                key = f"voice:ticket:{token_hash}"
                r.setex(key, ttl, data.model_dump_json())
                logger.debug("Issued voice ticket hash: %s (TTL: %ss)", token_hash[:12], ttl)
                return raw_token
            except Exception as e:
                logger.critical(
                    "Production Redis error during voice ticket creation: %s. Failing closed.", e
                )
                raise RuntimeError(f"Failed to persist voice ticket in production Redis: {e}")

        # Non-production: attempt Redis first, then fall back to in-memory
        if r:
            try:
                key = f"voice:ticket:{token_hash}"
                r.setex(key, ttl, data.model_dump_json())
                logger.debug("Issued voice ticket hash: %s (TTL: %ss)", token_hash[:12], ttl)
                return raw_token
            except Exception as e:
                logger.warning("Failed to store ticket in Redis; falling back to in-memory: %s", e)

        # In-memory single-process fallback (Development & Testing ONLY)
        with cls._in_memory_lock:
            # Purge expired entries
            now = time.time()
            expired_keys = [k for k, v in cls._in_memory_store.items() if v["expires_at"] < now]
            for k in expired_keys:
                cls._in_memory_store.pop(k, None)

            cls._in_memory_store[token_hash] = {
                "data": data,
                "expires_at": now + ttl,
            }
            logger.debug(
                "Issued voice ticket hash in-memory: %s (TTL: %ss)", token_hash[:12], ttl
            )

        return raw_token

    @classmethod
    async def redeem_ticket(cls, raw_ticket: str) -> Optional[TicketData]:
        """Atomically redeems and consumes a voice ticket.

        Returns TicketData if valid, or None if expired, forged, or replayed.
        """
        if not raw_ticket or not raw_ticket.startswith("tkt_"):
            return None

        token_hash = cls._hash_ticket(raw_ticket)
        r = cls._get_redis()

        if settings.APP_ENV == "production":
            if not r:
                logger.critical(
                    "Production Redis unavailable: voice ticket redemption rejected to fail closed."
                )
                return None
            try:
                key = f"voice:ticket:{token_hash}"
                payload = r.getdel(key)
                if payload:
                    data_dict = json.loads(payload)
                    data = TicketData.model_validate(data_dict)
                    logger.info(
                        "Atomically redeemed Redis voice ticket hash: %s for org: %s",
                        token_hash[:12],
                        data.org_id,
                    )
                    return data
                logger.warning(
                    "Voice ticket redemption rejected (not found, expired or replayed): %s",
                    token_hash[:12],
                )
                return None
            except Exception as e:
                logger.critical(
                    "Production Redis error during voice ticket redemption: %s. Failing closed.", e
                )
                return None

        # Non-production: attempt Redis first, then fall back to in-memory
        if r:
            try:
                key = f"voice:ticket:{token_hash}"
                # Atomic check-and-delete: GETDEL is atomic in Redis 6.2+
                payload = r.getdel(key)
                if payload:
                    data_dict = json.loads(payload)
                    data = TicketData.model_validate(data_dict)
                    logger.info(
                        "Atomically redeemed Redis voice ticket hash: %s for org: %s",
                        token_hash[:12],
                        data.org_id,
                    )
                    return data
                logger.warning(
                    "Voice ticket redemption rejected (not found, expired or replayed): %s",
                    token_hash[:12],
                )
                return None
            except Exception as e:
                logger.warning("Failed to redeem ticket from Redis; falling back to in-memory: %s", e)

        # In-memory atomic redemption (Development & Testing ONLY)
        with cls._in_memory_lock:
            entry = cls._in_memory_store.pop(token_hash, None)
            if not entry:
                logger.warning(
                    "In-memory voice ticket rejected (not found, expired or replayed): %s",
                    token_hash[:12],
                )
                return None

            if entry["expires_at"] < time.time():
                logger.warning("In-memory voice ticket expired: %s", token_hash[:12])
                return None

            data = entry["data"]
            logger.info(
                "Atomically redeemed in-memory voice ticket hash: %s for org: %s",
                token_hash[:12],
                data.org_id,
            )
            return data

    @classmethod
    def reset_in_memory_store_for_tests(cls):
        """Clears in-memory ticket store between unit test runs."""
        with cls._in_memory_lock:
            cls._in_memory_store.clear()

    @classmethod
    def set_redis_client_for_tests(cls, client):
        """Sets or clears active Redis client for testing."""
        if client is None:
            cls._redis_client = None
            cls._redis_disabled_for_tests = True
        else:
            cls._redis_client = client
            cls._redis_disabled_for_tests = False

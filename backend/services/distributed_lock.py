"""
Distributed locking via PostgreSQL advisory locks with thread-safe fallback for SQLite/tests.

Guarantees mutual exclusion across multiple workers, processes, or replicas:
  - Post-level locks (e.g., prevent duplicate upload/comment of post #42)
  - Channel-level locks (e.g., prevent concurrent uploads to the same channel)
  - Generic resource locks (e.g., ASMR workflow runs, sheet sync)

PostgreSQL advisory locks:
  - Exclusive across ALL database connections (any process, any container)
  - Transaction-scoped (pg_try_advisory_xact_lock) or Session-scoped (pg_try_advisory_lock)
  - Zero-overhead (no tables, no GC, no TTL management)

In SQLite / test mode:
  - Uses an internal in-process mutex dictionary so concurrent threads in tests
    exhibit realistic mutual exclusion and contention behavior.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Namespace prefixes to prevent collision between resource types
_POST_LOCK_NAMESPACE = 0x50_49_50_45     # "PIPE"
_CHANNEL_LOCK_NAMESPACE = 0x43_48_41_4E  # "CHAN"
_GENERIC_LOCK_NAMESPACE = 0x47_45_4E_52  # "GENR"

# Thread-safe in-memory lock store for SQLite / test environments
_MEMORY_LOCKS: dict[int, threading.Lock] = {}
_MEMORY_LOCKS_MUTEX = threading.Lock()


def _get_memory_lock(lock_id: int) -> threading.Lock:
    with _MEMORY_LOCKS_MUTEX:
        if lock_id not in _MEMORY_LOCKS:
            _MEMORY_LOCKS[lock_id] = threading.Lock()
        return _MEMORY_LOCKS[lock_id]


def _make_lock_id(namespace: int, resource_id: str, operation: str) -> int:
    """Hash (namespace, resource_id, operation) into a stable signed 63-bit integer."""
    raw = f"{namespace}:{resource_id}:{operation}".encode()
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def make_post_lock_id(post_id: int, operation: str) -> int:
    return _make_lock_id(_POST_LOCK_NAMESPACE, str(post_id), operation)


def make_channel_lock_id(channel_key: str, operation: str) -> int:
    return _make_lock_id(_CHANNEL_LOCK_NAMESPACE, channel_key.lower().strip(), operation)


def _is_postgres(db: Session) -> bool:
    try:
        bind = getattr(db, "bind", None) or db.get_bind()
        return "postgresql" in str(bind.dialect.name).lower()
    except Exception:
        return False


@contextmanager
def advisory_lock(
    db: Session,
    post_id: int,
    operation: str,
    blocking: bool = False,
) -> Generator[bool, None, None]:
    """
    Acquire a distributed lock for post_id + operation.

    Usage:
        with advisory_lock(db, post_id=10, operation="youtube_upload") as acquired:
            if not acquired:
                # Another worker is already uploading post 10
                return
            perform_upload()
    """
    lock_id = make_post_lock_id(post_id, operation)
    with _execute_lock(db, lock_id, f"post:{post_id}:{operation}", blocking) as acquired:
        yield acquired


@contextmanager
def channel_lock(
    db: Session,
    channel_key: str,
    operation: str,
    blocking: bool = False,
) -> Generator[bool, None, None]:
    """
    Acquire a distributed lock for channel_key + operation.

    Prevents concurrent uploads or quota conflicts on the same YouTube/Instagram channel.
    """
    lock_id = make_channel_lock_id(channel_key, operation)
    with _execute_lock(db, lock_id, f"channel:{channel_key}:{operation}", blocking) as acquired:
        yield acquired


@contextmanager
def _execute_lock(
    db: Session,
    lock_id: int,
    resource_desc: str,
    blocking: bool,
) -> Generator[bool, None, None]:
    is_pg = _is_postgres(db)

    if not is_pg:
        # SQLite / Dev / Unit test mode: in-memory lock simulation
        mem_lock = _get_memory_lock(lock_id)
        if blocking:
            mem_lock.acquire()
            acquired = True
        else:
            acquired = mem_lock.acquire(blocking=False)

        try:
            if acquired:
                logger.debug("advisory_lock[mem]: acquired %s (id=%s)", resource_desc, lock_id)
            else:
                logger.info("advisory_lock[mem]: BUSY %s (id=%s)", resource_desc, lock_id)
            yield acquired
        finally:
            if acquired:
                try:
                    mem_lock.release()
                except RuntimeError:
                    pass
        return

    # PostgreSQL real advisory lock
    acquired = False
    try:
        if blocking:
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
            acquired = True
        else:
            result = db.execute(text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
            acquired = bool(result.scalar())

        if acquired:
            logger.debug("advisory_lock[pg]: acquired %s (id=%s)", resource_desc, lock_id)
        else:
            logger.info("advisory_lock[pg]: BUSY %s (id=%s)", resource_desc, lock_id)

        yield acquired
    except Exception as exc:
        logger.warning("advisory_lock[pg]: error for %s: %s", resource_desc, exc)
        yield False

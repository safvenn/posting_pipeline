"""
Audit Log Service — structured, append-only security and admin audit trail.

All security-relevant events must go through this service.
Never log secrets, tokens, passwords, or PII.

Event type constants are defined here as the canonical reference.

Usage:
    from backend.services.audit import AuditService, AuthEvent, PostEvent

    audit = AuditService(db, actor="admin", actor_ip=request.client.host)

    # Record a login
    audit.log(AuthEvent.LOGIN_SUCCESS, description="Login from Chrome/Windows")

    # Record a post cancellation
    audit.log(
        PostEvent.POST_CANCELLED,
        resource_type="post",
        resource_id=str(post.id),
        description=f"Admin cancelled post {post.id}",
        details={"reason": "duplicate"},
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("audit")


# ---------------------------------------------------------------------------
# Event type namespaces
# ---------------------------------------------------------------------------

class AuthEvent:
    LOGIN_SUCCESS   = "LOGIN_SUCCESS"
    LOGIN_FAILURE   = "LOGIN_FAILURE"
    LOGOUT          = "LOGOUT"
    TOKEN_ROTATED   = "TOKEN_ROTATED"
    TOKEN_REVOKED   = "TOKEN_REVOKED"
    TOKEN_REVOKE_ALL = "TOKEN_REVOKE_ALL"
    TOKEN_REJECTED  = "TOKEN_REJECTED"   # invalid/expired token used


class PostEvent:
    POST_CREATED        = "POST_CREATED"
    POST_STATUS_CHANGED = "POST_STATUS_CHANGED"
    POST_RETRIED        = "POST_RETRIED"
    POST_CANCELLED      = "POST_CANCELLED"
    POST_DELETED        = "POST_DELETED"
    POST_UPLOADED       = "POST_UPLOADED"


class ConfigEvent:
    CHANNEL_CREATED     = "CHANNEL_CREATED"
    CHANNEL_UPDATED     = "CHANNEL_UPDATED"
    CHANNEL_DELETED     = "CHANNEL_DELETED"
    CREDS_ROTATED       = "CREDS_ROTATED"
    SETTING_TOGGLED     = "SETTING_TOGGLED"


class SystemEvent:
    WORKER_STARTED          = "WORKER_STARTED"
    WORKER_STOPPED          = "WORKER_STOPPED"
    MIGRATION_RUN           = "MIGRATION_RUN"
    JOB_DEAD_LETTERED       = "JOB_DEAD_LETTERED"
    JOB_RETRY               = "JOB_RETRY"
    JOB_CANCEL              = "JOB_CANCEL"
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"
    CIRCUIT_BREAKER_RESET   = "CIRCUIT_BREAKER_RESET"
    BULK_REQUEUE            = "BULK_REQUEUE"
    STALE_JOB_RECOVERED     = "STALE_JOB_RECOVERED"
    SECURITY_ALERT          = "SECURITY_ALERT"



# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------

class Outcome:
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED  = "denied"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AuditService:
    """
    Append-only audit log writer.

    Best-effort: any DB error is caught and logged to the structured logger
    so audit failures never disrupt the request/operation flow.
    """

    def __init__(
        self,
        db: Session,
        actor: str = "system",
        actor_ip: Optional[str] = None,
    ) -> None:
        self._db = db
        self._actor = actor
        self._actor_ip = actor_ip

    def log(
        self,
        event_type: str,
        outcome: str = Outcome.SUCCESS,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        description: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Write an audit log entry.

        Parameters
        ----------
        event_type : str
            One of the event type constants above (e.g., AuthEvent.LOGIN_SUCCESS).
        outcome : str
            One of 'success', 'failure', 'denied'.
        resource_type : str, optional
            The type of resource acted upon (e.g., "post", "channel", "setting").
        resource_id : str, optional
            The identifier of the resource (stringified primary key).
        description : str, optional
            Human-readable description of what happened.
        details : dict, optional
            Structured event details (before/after state, etc.).
            NEVER include secrets, tokens, or passwords.
        """
        # Emit structured log line first (survives DB failure)
        log_parts = [
            f"event={event_type}",
            f"outcome={outcome}",
            f"actor={self._actor}",
        ]
        if self._actor_ip:
            log_parts.append(f"ip={self._actor_ip}")
        if resource_type:
            log_parts.append(f"resource={resource_type}/{resource_id}")
        if description:
            log_parts.append(f"desc={description[:200]}")

        log_line = " ".join(log_parts)
        if outcome == Outcome.FAILURE:
            logger.warning(log_line)
        elif outcome == Outcome.DENIED:
            logger.warning(log_line)
        else:
            logger.info(log_line)

        # Persist to DB (best-effort)
        try:
            from backend.models import AuditLog
            entry = AuditLog(
                actor=self._actor,
                actor_ip=self._actor_ip,
                event_type=event_type,
                outcome=outcome,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                description=(description or "")[:2000] if description else None,
                details_json=json.dumps(details) if details else None,
                created_at=datetime.now(timezone.utc),
            )
            self._db.add(entry)
            self._db.commit()
        except Exception as exc:
            logger.warning("AuditLog DB write failed (non-fatal): %s", exc)
            try:
                self._db.rollback()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def login_success(self, username: str) -> None:
        self.log(AuthEvent.LOGIN_SUCCESS, description=f"Login: {username}")

    def login_failure(self, username: str, reason: str = "") -> None:
        self.log(
            AuthEvent.LOGIN_FAILURE,
            outcome=Outcome.FAILURE,
            description=f"Failed login for {username!r}: {reason}",
        )

    def logout(self, username: str) -> None:
        self.log(AuthEvent.LOGOUT, description=f"Logout: {username}")

    def token_rotated(self, username: str) -> None:
        self.log(AuthEvent.TOKEN_ROTATED, description=f"Refresh token rotated for {username}")

    def token_revoke_all(self, username: str) -> None:
        self.log(AuthEvent.TOKEN_REVOKE_ALL, description=f"All tokens revoked for {username}")

    def token_rejected(self, reason: str) -> None:
        self.log(
            AuthEvent.TOKEN_REJECTED,
            outcome=Outcome.DENIED,
            description=f"Token rejected: {reason}",
        )

    def post_status_changed(
        self,
        post_id: int,
        from_status: str,
        to_status: str,
        reason: str = "",
    ) -> None:
        self.log(
            PostEvent.POST_STATUS_CHANGED,
            resource_type="post",
            resource_id=str(post_id),
            description=f"Post {post_id}: {from_status} → {to_status}" + (f" ({reason})" if reason else ""),
            details={"from": from_status, "to": to_status, "reason": reason},
        )

    def setting_toggled(self, key: str, new_value: str) -> None:
        self.log(
            ConfigEvent.SETTING_TOGGLED,
            resource_type="setting",
            resource_id=key,
            description=f"Setting {key!r} changed to {new_value!r}",
            details={"key": key, "new_value": new_value},
        )


def system_audit(event_type: str, description: str, details: Optional[dict] = None) -> None:
    """
    Write a system-level audit event without a DB session.
    Used at startup/shutdown where no DB session is available.
    Logs only to the structured logger.
    """
    log_parts = [f"event={event_type}", f"actor=system"]
    if description:
        log_parts.append(f"desc={description[:200]}")
    logger.info(" ".join(log_parts))

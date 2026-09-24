"""Domain error hierarchy.

Maps cleanly to HTTP status codes in the API layer without leaking
implementation details.  All application-layer exceptions should
inherit from DomainError or one of its subclasses.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all application domain errors."""
    http_status: int = 500
    error_code: str = "internal_error"


class ValidationError(DomainError):
    http_status = 422
    error_code = "validation_error"


class AuthenticationError(DomainError):
    http_status = 401
    error_code = "authentication_required"


class AuthorizationError(DomainError):
    http_status = 403
    error_code = "forbidden"


class NotFoundError(DomainError):
    http_status = 404
    error_code = "not_found"


class ConflictError(DomainError):
    http_status = 409
    error_code = "conflict"


class RateLimitError(DomainError):
    http_status = 429
    error_code = "rate_limit_exceeded"


class WorkflowTransitionError(DomainError):
    http_status = 409
    error_code = "workflow_transition_error"


class IdempotencyConflictError(DomainError):
    http_status = 409
    error_code = "idempotency_conflict"


class ProviderError(DomainError):
    http_status = 502
    error_code = "provider_error"

    def __init__(self, message: str, provider: str | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class RetryableProviderError(ProviderError):
    """Provider error that can be safely retried (network timeout, 5xx, etc.)."""
    error_code = "provider_retryable_error"

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message, provider=provider, retryable=True)


class PermanentProviderError(ProviderError):
    """Provider error that must NOT be retried (auth failure, invalid input, etc.)."""
    error_code = "provider_permanent_error"

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message, provider=provider, retryable=False)


class QuotaExceededError(ProviderError):
    """Provider daily/hourly quota exhausted — retry later but not immediately."""
    http_status = 429
    error_code = "quota_exceeded"

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message, provider=provider, retryable=True)


class StorageError(DomainError):
    http_status = 500
    error_code = "storage_error"


class ConfigurationError(DomainError):
    """Required configuration missing or invalid at startup."""
    http_status = 500
    error_code = "configuration_error"

"""
Tests for the post state machine.

Covers:
  - All legal transitions
  - All illegal transitions  
  - Terminal states
  - Active states
  - Retryable states
  - validate_transition raises on illegal transition
"""
from __future__ import annotations

import pytest

from backend.domain.states import (
    PostStatus,
    InvalidTransitionError,
    is_valid_transition,
    validate_transition,
    terminal_states,
    active_states,
    retryable_states,
)


class TestLegalTransitions:
    """Every legal transition in the state machine."""

    def test_queued_to_cleaning(self):
        assert is_valid_transition("queued", "cleaning")

    def test_queued_to_cleaned_skip(self):
        assert is_valid_transition("queued", "cleaned")  # watermark toggle off

    def test_queued_to_failed(self):
        assert is_valid_transition("queued", "failed")

    def test_queued_to_cancelled(self):
        assert is_valid_transition("queued", "cancelled")

    def test_cleaning_to_cleaned(self):
        assert is_valid_transition("cleaning", "cleaned")

    def test_cleaning_to_queued_retry(self):
        assert is_valid_transition("cleaning", "queued")

    def test_cleaning_to_failed(self):
        assert is_valid_transition("cleaning", "failed")

    def test_cleaned_to_scheduled(self):
        assert is_valid_transition("cleaned", "scheduled")

    def test_cleaned_to_failed(self):
        assert is_valid_transition("cleaned", "failed")

    def test_scheduled_to_uploading(self):
        assert is_valid_transition("scheduled", "uploading")

    def test_scheduled_to_uploaded_direct(self):
        assert is_valid_transition("scheduled", "uploaded")

    def test_scheduled_to_queued_retry(self):
        assert is_valid_transition("scheduled", "queued")

    def test_scheduled_to_failed(self):
        assert is_valid_transition("scheduled", "failed")

    def test_scheduled_to_cancelled(self):
        assert is_valid_transition("scheduled", "cancelled")

    def test_uploading_to_uploaded(self):
        assert is_valid_transition("uploading", "uploaded")

    def test_uploading_to_scheduled_retry(self):
        assert is_valid_transition("uploading", "scheduled")

    def test_uploading_to_failed(self):
        assert is_valid_transition("uploading", "failed")

    def test_uploaded_to_commented(self):
        assert is_valid_transition("uploaded", "commented")

    def test_uploaded_to_failed(self):
        assert is_valid_transition("uploaded", "failed")

    def test_commented_to_failed(self):
        assert is_valid_transition("commented", "failed")

    def test_failed_to_queued_retry(self):
        assert is_valid_transition("failed", "queued")

    def test_failed_to_cancelled(self):
        assert is_valid_transition("failed", "cancelled")


class TestIllegalTransitions:
    """Critical: these must be blocked to prevent corruption."""

    def test_queued_to_uploaded_illegal(self):
        assert not is_valid_transition("queued", "uploaded")

    def test_queued_to_commented_illegal(self):
        assert not is_valid_transition("queued", "commented")

    def test_cleaning_to_commented_illegal(self):
        assert not is_valid_transition("cleaning", "commented")

    def test_cleaned_to_uploading_illegal(self):
        assert not is_valid_transition("cleaned", "uploading")

    def test_uploaded_to_queued_illegal(self):
        assert not is_valid_transition("uploaded", "queued")

    def test_commented_to_queued_illegal(self):
        assert not is_valid_transition("commented", "queued")

    def test_commented_to_scheduled_illegal(self):
        assert not is_valid_transition("commented", "scheduled")

    def test_cancelled_to_queued_illegal(self):
        """Terminal state — cannot leave cancelled."""
        assert not is_valid_transition("cancelled", "queued")

    def test_cancelled_to_any_illegal(self):
        for target in PostStatus:
            assert not is_valid_transition("cancelled", target.value)

    def test_unknown_source_state(self):
        assert not is_valid_transition("unknown_state", "queued")

    def test_unknown_target_state(self):
        assert not is_valid_transition("queued", "unknown_state")

    def test_both_unknown(self):
        assert not is_valid_transition("not_a_state", "also_not_a_state")


class TestValidateTransitionRaises:
    """validate_transition must raise InvalidTransitionError for illegal transitions."""

    def test_raises_for_illegal_transition(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition("queued", "commented")
        assert "queued" in str(exc_info.value)
        assert "commented" in str(exc_info.value)

    def test_raises_includes_post_id(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition("queued", "commented", post_id=182)
        assert "182" in str(exc_info.value)

    def test_does_not_raise_for_legal_transition(self):
        # Must not raise
        validate_transition("queued", "cleaning")
        validate_transition("cleaned", "scheduled")
        validate_transition("failed", "queued")

    def test_error_attributes(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition("cancelled", "queued", post_id=999)
        err = exc_info.value
        assert err.from_state == "cancelled"
        assert err.to_state == "queued"
        assert err.post_id == 999


class TestStateCategories:
    """Test state classification functions."""

    def test_terminal_states(self):
        terminals = terminal_states()
        assert "commented" in terminals
        assert "cancelled" in terminals
        # Non-terminal states must NOT be in terminals
        assert "queued" not in terminals
        assert "failed" not in terminals
        assert "scheduled" not in terminals

    def test_active_states(self):
        actives = active_states()
        assert "cleaning" in actives
        assert "uploading" in actives
        # Idle states must NOT be in active
        assert "queued" not in actives
        assert "cleaned" not in actives

    def test_retryable_states(self):
        retryable = retryable_states()
        assert "failed" in retryable
        assert "queued" not in retryable
        assert "commented" not in retryable


class TestPostStatusEnum:
    """PostStatus enum values match the database strings."""

    def test_status_values_are_strings(self):
        for status in PostStatus:
            assert isinstance(status.value, str)

    def test_status_is_lowercase(self):
        for status in PostStatus:
            assert status.value == status.value.lower()

    def test_enum_membership(self):
        assert PostStatus("queued") == PostStatus.QUEUED
        assert PostStatus("failed") == PostStatus.FAILED
        assert PostStatus("commented") == PostStatus.COMMENTED

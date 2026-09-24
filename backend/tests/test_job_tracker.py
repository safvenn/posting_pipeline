"""
Tests for the JobTracker context manager.

Covers:
  - Successful job creates a SUCCEEDED record
  - Exception inside with-block creates a FAILED record with error message
  - Tracker is NOOP when DB is unavailable (never raises)
  - set_output captures output and external_ref
  - Nested exceptions propagate correctly (tracker doesn't swallow them)
  - Attempt counting increments correctly
  - Input data is forwarded to Job.create
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# Correct patch paths: SessionLocal and JobRepository are imported *inside*
# the job_tracker module via lazy imports, so we patch them at their
# source module paths which Python resolves before the local import executes.
_SESSIONLOCAL_PATH = "backend.database.SessionLocal"
_JOB_REPO_PATH = "backend.repositories.job_repository.JobRepository"


def _make_mocks():
    """Return (mock_db, mock_repo, mock_job) ready for patching."""
    mock_job = MagicMock()
    mock_job.id = 1
    mock_repo = MagicMock()
    mock_repo.create.return_value = mock_job
    mock_repo.count_attempts.return_value = 0
    mock_db = MagicMock()
    return mock_db, mock_repo, mock_job


class TestJobTrackerSuccess:
    """Successful execution path."""

    def test_successful_block_calls_succeed(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="youtube_upload") as tracker:
                pass  # no exception

        mock_repo.start.assert_called_once_with(mock_job)
        mock_repo.succeed.assert_called_once()
        mock_repo.fail.assert_not_called()

    def test_set_output_passes_data_to_succeed(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="youtube_upload") as tracker:
                tracker.set_output({"video_id": "abc123"}, external_ref="abc123")

        call_kwargs = mock_repo.succeed.call_args[1]
        assert call_kwargs["output"] == {"video_id": "abc123"}
        assert call_kwargs["external_ref"] == "abc123"

    def test_set_external_ref_works(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="youtube_upload") as tracker:
                tracker.set_external_ref("yt_video_abc")

        call_kwargs = mock_repo.succeed.call_args[1]
        assert call_kwargs["external_ref"] == "yt_video_abc"

    def test_db_is_closed_after_success(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="youtube_upload"):
                pass

        mock_db.close.assert_called_once()


class TestJobTrackerFailure:
    """Exception path."""

    def test_exception_calls_fail(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(ValueError):
                with JobTracker(post_id=182, job_type="youtube_upload"):
                    raise ValueError("Upload quota exceeded")

        mock_repo.fail.assert_called_once()
        fail_args = mock_repo.fail.call_args
        error_str = fail_args[1].get("error", "") or (fail_args[0][1] if len(fail_args[0]) > 1 else "")
        assert "ValueError" in error_str or "quota" in error_str.lower()

    def test_exception_propagates_to_caller(self):
        """The tracker must NOT swallow exceptions."""
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(RuntimeError, match="SSH timeout"):
                with JobTracker(post_id=99, job_type="clean"):
                    raise RuntimeError("SSH timeout")

    def test_fail_receives_exception_object(self):
        mock_db, mock_repo, mock_job = _make_mocks()
        exc = ConnectionError("Drive upload failed")

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(ConnectionError):
                with JobTracker(post_id=42, job_type="drive_archive"):
                    raise exc

        fail_kwargs = mock_repo.fail.call_args[1]
        assert fail_kwargs["exc"] is exc

    def test_succeed_not_called_on_failure(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(Exception):
                with JobTracker(post_id=182, job_type="enrich"):
                    raise Exception("Gemini error")

        mock_repo.succeed.assert_not_called()
        mock_repo.fail.assert_called_once()

    def test_db_is_closed_after_exception(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(Exception):
                with JobTracker(post_id=182, job_type="enrich"):
                    raise Exception("error")

        mock_db.close.assert_called_once()


class TestJobTrackerNoop:
    """NOOP mode when DB is unavailable."""

    def test_noop_when_db_unavailable(self):
        """Should not raise even if DB session fails."""
        with patch("backend.services.job_tracker.SessionLocal", side_effect=Exception("DB down")):
            from backend.services.job_tracker import JobTracker
            # Must not raise
            with JobTracker(post_id=182, job_type="youtube_upload") as tracker:
                tracker.set_output({"video_id": "abc"})
                tracker.set_external_ref("abc")

    def test_noop_tracker_methods_are_safe(self):
        from backend.services.job_tracker import _NoopTracker
        t = _NoopTracker()
        t.set_output({"some": "data"}, external_ref="ref123")
        t.set_external_ref("another_ref")

    def test_exception_still_propagates_in_noop_mode(self):
        """Even in NOOP mode, exceptions from the with-block must propagate."""
        with patch("backend.services.job_tracker.SessionLocal", side_effect=Exception("DB down")):
            from backend.services.job_tracker import JobTracker
            with pytest.raises(ValueError, match="business error"):
                with JobTracker(post_id=182, job_type="enrich"):
                    raise ValueError("business error")

    def test_noop_when_job_repo_unavailable(self):
        """NOOP if JobRepository constructor fails."""
        mock_db = MagicMock()
        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", side_effect=Exception("import error")):
            from backend.services.job_tracker import JobTracker
            # Must not raise
            with JobTracker(post_id=182, job_type="youtube_upload") as tracker:
                pass


class TestJobTrackerAttemptCounting:
    """Attempt counting increments correctly."""

    def test_attempt_is_count_plus_one(self):
        mock_db, mock_repo, mock_job = _make_mocks()
        mock_repo.count_attempts.return_value = 2  # 2 previous attempts

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="youtube_upload"):
                pass

        create_kwargs = mock_repo.create.call_args[1]
        assert create_kwargs["attempt"] == 3

    def test_none_post_id_skips_attempt_count(self):
        """System-level jobs (post_id=None) always use attempt=1."""
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=None, job_type="asmr_workflow"):
                pass

        create_kwargs = mock_repo.create.call_args[1]
        assert create_kwargs["attempt"] == 1
        mock_repo.count_attempts.assert_not_called()


class TestJobTrackerInputData:
    """Input data is passed to Job.create."""

    def test_input_data_passed_to_create(self):
        mock_db, mock_repo, mock_job = _make_mocks()

        with patch("backend.services.job_tracker.SessionLocal", return_value=mock_db), \
             patch("backend.services.job_tracker.JobRepository", return_value=mock_repo):
            from backend.services.job_tracker import JobTracker
            with JobTracker(post_id=182, job_type="clean", input_data={"channel": "test_channel"}):
                pass

        create_kwargs = mock_repo.create.call_args[1]
        assert create_kwargs["input_data"] == {"channel": "test_channel"}

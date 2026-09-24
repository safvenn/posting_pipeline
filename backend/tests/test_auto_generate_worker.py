import pytest
import httpx
from unittest.mock import MagicMock, patch
from backend.jobs.auto_generate_worker import PipelineClient, run_worker_batch

def test_pipeline_client_uses_api_health_for_ping():
    """Verify ping checks /api/health instead of 404 /health."""
    client = PipelineClient(base_url="https://test-pipeline.com", api_key="secret")
    with patch.object(httpx.Client, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        assert client.ping() is True
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://test-pipeline.com/api/health"

def test_pipeline_client_warmup_retries_until_success():
    """Verify warmup retries when Render cold-start returns initial timeouts or errors."""
    client = PipelineClient(base_url="https://test-pipeline.com", api_key="secret")
    call_count = 0
    
    def side_effect(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ReadTimeout("Cold start waiting...")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        return mock_resp

    with patch.object(httpx.Client, "get", side_effect=side_effect):
        with patch("time.sleep", return_value=None):
            warmed = client.warmup(max_attempts=3, backoff_sec=1)
            assert warmed is True
            assert call_count == 3

def test_fetch_pending_queue_retries_on_timeout():
    """Verify fetch_pending_queue retries on timeout before succeeding."""
    client = PipelineClient(base_url="https://test-pipeline.com", api_key="secret")
    attempts = 0

    def mock_get(url, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("Cold start read timeout")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rows": [{"id": "71", "prompt": "test prompt", "title": "Test"}]
        }
        return mock_resp

    with patch.object(httpx.Client, "get", side_effect=mock_get):
        with patch("time.sleep", return_value=None):
            items = client.fetch_pending_queue(channel="the_indian_kitchen", max_retries=3)
            assert len(items) == 1
            assert items[0].id == "71"
            assert attempts == 2

def test_fetch_pending_queue_raises_after_max_retries():
    """Verify fetch_pending_queue raises error after exhausting retries instead of swallowing."""
    client = PipelineClient(base_url="https://test-pipeline.com", api_key="secret")

    with patch.object(httpx.Client, "get", side_effect=httpx.ReadTimeout("Persistent timeout")):
        with patch("time.sleep", return_value=None):
            with pytest.raises(httpx.ReadTimeout):
                client.fetch_pending_queue(channel="the_indian_kitchen", max_retries=2)

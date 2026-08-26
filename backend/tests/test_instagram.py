"""
Unit tests for Instagram Graph API service and Reels publishing.
"""
from unittest.mock import MagicMock, patch
import pytest

from backend.models import ChannelConfig, Post
from backend.services.instagram import (
    format_instagram_caption,
    verify_instagram_credentials,
    sanitize_instagram_credentials,
    create_reels_container,
    wait_for_container_ready,
    publish_container,
    publish_reel_for_post,
)


def test_sanitize_instagram_credentials():
    # 1. Full Graph API URL in access_token
    raw_url = "https://graph.facebook.com/v21.0/178414000000000?fields=id&access_token=EAAG123456789abcdef"
    acc_id, token = sanitize_instagram_credentials("178414000000000", raw_url)
    assert token == "EAAG123456789abcdef"
    assert acc_id == "178414000000000"

    # 2. Bearer prefix and quotes
    acc_id, token = sanitize_instagram_credentials(" 178414000000000 ", "Bearer EAAG99999 ;")
    assert token == "EAAG99999"
    assert acc_id == "178414000000000"

    # 3. URL in account_id field
    acc_id, token = sanitize_instagram_credentials("https://graph.facebook.com/v21.0/178414999999999?access_token=EAAG777", "")
    assert acc_id == "178414999999999"
    assert token == "EAAG777"



def test_format_instagram_caption():
    title = "World's Tiniest Dosa! ASMR"
    description = "Subscribe to our channel for more tiny food! Miniature cooking ASMR."
    tags = "dosa; miniature cooking; tiny food"

    caption = format_instagram_caption(title, description, tags)
    assert "World's Tiniest Dosa!" in caption
    assert "Subscribe to our channel" not in caption
    assert "#dosa" in caption
    assert "#miniaturecooking" in caption
    assert "#reels" in caption


def test_instagram_connection_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "178414000000000",
        "username": "the_indian_kitchen_asmr",
        "name": "The Indian Kitchen",
        "profile_picture_url": "https://example.com/pic.jpg",
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        res = verify_instagram_credentials("178414000000000", "test_token_123")
        assert res["success"] is True
        assert res["username"] == "the_indian_kitchen_asmr"
        assert "@the_indian_kitchen_asmr" in res["message"]


def test_instagram_connection_invalid_credentials():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {"message": "Invalid OAuth access token."}
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        res = verify_instagram_credentials("178414000000000", "invalid_token")
        assert res["success"] is False
        assert "Invalid OAuth access token" in res["message"]


def test_create_reels_container():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "container_12345",
        "uri": "https://rupload.facebook.com/ig-reels-upload/v21.0/container_12345",
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = create_reels_container(
            account_id="178414000000000",
            access_token="test_token",
            caption="Test Caption",
        )
        assert res["id"] == "container_12345"
        assert "rupload.facebook.com" in res["uri"]


def test_wait_for_container_ready():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status_code": "FINISHED"}

    with patch("httpx.Client.get", return_value=mock_resp):
        assert wait_for_container_ready("container_12345", "test_token") is True


def test_publish_container():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "media_98765"}

    with patch("httpx.Client.post", return_value=mock_resp):
        media_id = publish_container("178414000000000", "test_token", "container_12345")
        assert media_id == "media_98765"


def test_publish_reel_skipped_when_disabled():
    db = MagicMock()
    mock_channel = ChannelConfig(
        key="channel_a",
        display_name="Channel A",
        instagram_enabled=False,
    )
    db.query.return_value.filter.return_value.first.return_value = mock_channel

    post = Post(id=1, channel="channel_a", title="Test Post", video_path="video.mp4")
    res = publish_reel_for_post(post, db)
    assert res.get("skipped") is True

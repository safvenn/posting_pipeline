"""
Unit tests reproducing defects in Instagram scheduled publishing:
1. publish_reel_for_post fails when video file is missing even if container_id is pre-created and ready.
2. get_next_instagram_publishable_post_id suffers from head-of-line blocking on old failed posts.
3. Lack of max-retry / permanently_failed status causes infinite retry loops.
4. Naive datetimes (IST) normalized incorrectly to UTC.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, ChannelConfig, Post
from backend.jobs.instagram_job import (
    _to_utc_aware,
    get_next_instagram_publishable_post_id,
    MAX_INSTAGRAM_RETRIES,
)
from backend.services.instagram import publish_reel_for_post


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create active Instagram channel
    channel = ChannelConfig(
        key="the_indian_kitchen",
        display_name="The Indian Kitchen",
        instagram_enabled=True,
        instagram_account_id="178414000000000",
        instagram_access_token="EAAG_test_token",
        is_active=True,
    )
    session.add(channel)
    session.commit()

    yield session
    session.close()


def test_publish_reel_uses_precreated_container_when_video_file_missing(test_db):
    """
    REGRESSION TEST:
    If a post has a pre-created container (instagram_status='container_ready',
    instagram_container_id='cont_123'), publish_reel_for_post MUST proceed to
    publish that container even if the local video file was deleted (e.g. Render restart).
    """
    post = Post(
        channel="the_indian_kitchen",
        title="Test Reel",
        status="commented",
        youtube_video_id="yt_123",
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        instagram_status="container_ready",
        instagram_container_id="cont_123",
        clean_video_path="/nonexistent/path/video.mp4",
        video_path="/nonexistent/path/video_raw.mp4",
        clean_drive_file_id=None,
        drive_file_id=None,
    )
    test_db.add(post)
    test_db.commit()
    test_db.refresh(post)

    with patch("backend.services.instagram.wait_for_container_ready", return_value=True), \
         patch("backend.services.instagram.publish_container", return_value="media_published_999"), \
         patch("backend.services.instagram.fetch_media_permalink", return_value="https://instagram.com/reel/media_published_999/"):

        res = publish_reel_for_post(post, test_db)

        assert res.get("success") is True, f"Expected success but got: {res}"
        assert res.get("media_id") == "media_published_999"
        assert post.instagram_status == "published"
        assert post.instagram_media_id == "media_published_999"
        assert post.instagram_post_url == "https://instagram.com/reel/media_published_999/"


def test_get_next_instagram_publishable_post_id_skips_permanently_failed(test_db):
    """
    REGRESSION TEST:
    An old failed post with max retries or status 'permanently_failed' must NOT
    block newer, ready posts from being selected.
    """
    now = datetime.now(timezone.utc)

    # Post 1: Old failed post that exceeded max retries
    post_old = Post(
        channel="the_indian_kitchen",
        title="Old Failed Post",
        status="commented",
        youtube_video_id="yt_old",
        scheduled_at=now - timedelta(days=5),
        instagram_status="failed",
        retry_count=MAX_INSTAGRAM_RETRIES,
        updated_at=now - timedelta(days=5),
        video_path="/dummy/video.mp4",
    )
    test_db.add(post_old)

    # Post 2: Valid ready post due right now
    post_ready = Post(
        channel="the_indian_kitchen",
        title="Ready Post",
        status="commented",
        youtube_video_id="yt_ready",
        scheduled_at=now - timedelta(minutes=10),
        instagram_status="container_ready",
        instagram_container_id="cont_ready_456",
        retry_count=0,
        updated_at=now - timedelta(minutes=10),
        video_path="/dummy/video2.mp4",
    )
    test_db.add(post_ready)
    test_db.commit()

    with patch("backend.jobs.instagram_job.SessionLocal", return_value=test_db):
        selected_id = get_next_instagram_publishable_post_id()
        assert selected_id == post_ready.id, f"Expected post {post_ready.id} but got {selected_id}"


def test_get_next_instagram_publishable_post_id_prioritizes_container_ready_over_failed(test_db):
    """
    REGRESSION TEST:
    Even if an older failed post is still within retry attempts, a 'container_ready'
    post due right now should be prioritized over a failed retry to prevent queue starvation.
    """
    now = datetime.now(timezone.utc)

    post_retry = Post(
        channel="the_indian_kitchen",
        title="Failing Post",
        status="commented",
        youtube_video_id="yt_retry",
        scheduled_at=now - timedelta(days=2),
        instagram_status="failed",
        retry_count=1,
        updated_at=now - timedelta(hours=2),
        video_path="/dummy/video_retry.mp4",
    )
    test_db.add(post_retry)

    post_fresh = Post(
        channel="the_indian_kitchen",
        title="Fresh Container Ready Post",
        status="commented",
        youtube_video_id="yt_fresh",
        scheduled_at=now - timedelta(minutes=10),
        instagram_status="container_ready",
        instagram_container_id="cont_fresh_789",
        retry_count=0,
        updated_at=now - timedelta(minutes=10),
        video_path="/dummy/video_fresh.mp4",
    )
    test_db.add(post_fresh)
    test_db.commit()

    with patch("backend.jobs.instagram_job.SessionLocal", return_value=test_db):
        selected_id = get_next_instagram_publishable_post_id()
        assert selected_id == post_fresh.id, f"Expected container_ready post {post_fresh.id} but got {selected_id}"


def test_publish_reel_increments_retry_count_and_sets_permanently_failed(test_db):
    """
    REGRESSION TEST:
    When publish_reel_for_post fails on a post with no container and no video file,
    it must increment retry_count and mark permanently_failed when reaching MAX_INSTAGRAM_RETRIES.
    """
    post = Post(
        channel="the_indian_kitchen",
        title="Hopeless Post",
        status="commented",
        youtube_video_id="yt_hopeless",
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        instagram_status="failed",
        retry_count=MAX_INSTAGRAM_RETRIES - 1,  # 2
        clean_video_path="/nonexistent.mp4",
        video_path="/nonexistent_raw.mp4",
    )
    test_db.add(post)
    test_db.commit()

    res = publish_reel_for_post(post, test_db)
    assert res.get("success") is False
    assert post.retry_count >= MAX_INSTAGRAM_RETRIES
    assert post.instagram_status == "permanently_failed"


def test_to_utc_aware_converts_naive_ist():
    """
    REGRESSION TEST:
    Naive datetimes in this pipeline represent IST (Asia/Kolkata).
    12:30 PM IST must be normalized to 07:00 AM UTC, not 12:30 PM UTC!
    """
    naive_dt = datetime(2026, 10, 1, 12, 30, 0)
    utc_dt = _to_utc_aware(naive_dt)

    assert utc_dt.tzinfo == timezone.utc
    assert utc_dt.hour == 7
    assert utc_dt.minute == 0

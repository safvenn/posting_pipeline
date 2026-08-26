"""
Instagram Graph API v21.0 Service — handles Instagram Reels publishing,
resumable binary video uploads, container status polling, and per-channel authentication.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.models import ChannelConfig, Post

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def format_instagram_caption(title: str, description: str, tags: list[str] | str) -> str:
    """
    Format a high-engagement Instagram Reel caption from enriched metadata.
    Combines hook title, description body, and #hashtags.
    """
    parts = []
    if title:
        parts.append(title.strip())

    if description:
        # Filter out YouTube-specific CTAs or clean up description
        desc_clean = description.replace("Subscribe to our channel", "Follow for more delicious miniature creations!")
        desc_clean = desc_clean.replace("subscribe for more", "follow for more")
        parts.append(desc_clean.strip())

    # Format tags as Instagram hashtags
    tag_list: list[str] = []
    if isinstance(tags, str):
        tag_list = [t.strip() for t in tags.replace(",", ";").split(";") if t.strip()]
    elif isinstance(tags, list):
        tag_list = [str(t).strip() for t in tags if str(t).strip()]

    hashtags = []
    for t in tag_list:
        clean_tag = "".join(c for c in t if c.isalnum() or c == "_")
        if clean_tag and not clean_tag.startswith("#"):
            hashtags.append(f"#{clean_tag}")
        elif clean_tag.startswith("#"):
            hashtags.append(clean_tag)

    # Always ensure popular food / reels hashtags
    default_tags = ["#reels", "#reelsinstagram", "#asmrcooking", "#tinyfood", "#miniaturefood", "#foodie"]
    for dt in default_tags:
        if dt not in hashtags and len(hashtags) < 25:
            hashtags.append(dt)

    if hashtags:
        parts.append(" ".join(hashtags[:25]))

    return "\n\n".join(parts)


import re
import urllib.parse


def sanitize_instagram_credentials(account_id: str, access_token: str) -> tuple[str, str]:
    """
    Sanitize raw user inputs which may contain full Graph API URLs, query strings,
    or 'Bearer ' / 'OAuth ' prefixes.
    """
    account_id = (account_id or "").strip()
    access_token = (access_token or "").strip()

    # 1. If access_token contains a full Graph API URL or query string
    if "access_token=" in access_token:
        match = re.search(r'access_token=([^&\s]+)', access_token)
        if match:
            access_token = match.group(1)
    elif access_token.startswith("http://") or access_token.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(access_token)
            qs = urllib.parse.parse_qs(parsed.query)
            if "access_token" in qs and qs["access_token"]:
                access_token = qs["access_token"][0]
            if not account_id and parsed.path:
                path_parts = [p for p in parsed.path.strip("/").split("/") if p and not p.startswith("v")]
                if path_parts:
                    account_id = path_parts[-1]
        except Exception:
            pass

    # Clean up prefixes from access token
    access_token = access_token.replace("Bearer ", "").replace("OAuth ", "").replace("access_token=", "").strip()
    access_token = access_token.strip("\"'`; \r\n")

    # 2. If account_id contains a full Graph API URL
    if account_id.startswith("http://") or account_id.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(account_id)
            qs = urllib.parse.parse_qs(parsed.query)
            if not access_token and "access_token" in qs and qs["access_token"]:
                access_token = qs["access_token"][0]
            path_parts = [p for p in parsed.path.strip("/").split("/") if p and not p.startswith("v")]
            if path_parts:
                account_id = path_parts[-1]
        except Exception:
            pass

    if "access_token=" in account_id:
        match = re.search(r'access_token=([^&\s]+)', account_id)
        if match and not access_token:
            access_token = match.group(1)
        account_id = re.sub(r'[?&]?access_token=[^&\s]+', '', account_id).strip()

    account_id = account_id.strip("\"'`; \r\n")
    return account_id, access_token


def get_graph_base(access_token: str) -> str:
    """
    Return base URL for Graph API based on token type:
    - Instagram User Token (IGAA..., IGQJ...): https://graph.instagram.com/v21.0
    - Meta Business/Page Token (EAAG..., EAA...): https://graph.facebook.com/v21.0
    """
    if access_token.startswith("IG"):
        return "https://graph.instagram.com/v21.0"
    return GRAPH_API_BASE


def verify_instagram_credentials(account_id: str, access_token: str) -> dict:
    """
    Verify Instagram Business/Creator account credentials with Meta Graph API.
    Seamlessly handles:
    1. Instagram Direct User Tokens (IGAA...) via graph.instagram.com/me
    2. Meta Business Tokens (EAAG...) via graph.facebook.com
    3. Auto-discovery of Instagram account from Facebook Pages or /me/accounts
    """
    account_id, access_token = sanitize_instagram_credentials(account_id, access_token)

    if not access_token:
        return {
            "success": False,
            "message": "Access Token is missing or could not be parsed from input.",
        }

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        with httpx.Client(timeout=15.0) as client:
            # 1. Check graph.instagram.com for Instagram User Tokens (e.g. IGAA...)
            if access_token.startswith("IG"):
                ig_me_url = "https://graph.instagram.com/me"
                resp = client.get(
                    ig_me_url,
                    params={"fields": "id,username,name,profile_picture_url,account_type", "access_token": access_token},
                )
                data = resp.json()
                if resp.status_code == 200 and "username" in data:
                    return {
                        "success": True,
                        "account_id": str(data.get("id")),
                        "username": data.get("username"),
                        "name": data.get("name") or data.get("username"),
                        "profile_picture_url": data.get("profile_picture_url"),
                        "message": f"Successfully connected to @{data.get('username')}",
                    }
                elif "error" in data:
                    err_msg = data.get("error", {}).get("message", resp.text)
                    return {"success": False, "message": f"Instagram API error: {err_msg}"}

            # 2. Direct Instagram Account Check if account_id is provided and not 'me'
            if account_id and account_id.lower() not in ("me", "null", "none"):
                # Try graph.instagram.com first if account_id looks like an IG ID
                ig_url = f"https://graph.instagram.com/v21.0/{account_id}"
                ig_resp = client.get(
                    ig_url,
                    params={"fields": "id,username,name,profile_picture_url,account_type", "access_token": access_token},
                )
                ig_data = ig_resp.json()
                if ig_resp.status_code == 200 and "username" in ig_data:
                    return {
                        "success": True,
                        "account_id": str(ig_data.get("id")),
                        "username": ig_data.get("username"),
                        "name": ig_data.get("name") or ig_data.get("username"),
                        "profile_picture_url": ig_data.get("profile_picture_url"),
                        "message": f"Successfully connected to @{ig_data.get('username')}",
                    }

                # Try graph.facebook.com
                fb_url = f"{GRAPH_API_BASE}/{account_id}"
                resp = client.get(fb_url, params={"fields": "id,username,name,profile_picture_url"}, headers=headers)
                data = resp.json()
                if resp.status_code == 200 and "username" in data:
                    return {
                        "success": True,
                        "account_id": str(data.get("id")),
                        "username": data.get("username"),
                        "name": data.get("name") or data.get("username"),
                        "profile_picture_url": data.get("profile_picture_url"),
                        "message": f"Successfully connected to @{data.get('username')}",
                    }

                # If account_id is a Facebook Page ID, try looking for instagram_business_account
                page_resp = client.get(
                    fb_url,
                    params={"fields": "id,name,instagram_business_account{id,username,name,profile_picture_url}"},
                    headers=headers,
                )
                page_data = page_resp.json()
                if page_resp.status_code == 200 and "instagram_business_account" in page_data:
                    ig_acc = page_data["instagram_business_account"]
                    return {
                        "success": True,
                        "account_id": str(ig_acc.get("id")),
                        "username": ig_acc.get("username"),
                        "name": ig_acc.get("name") or ig_acc.get("username"),
                        "profile_picture_url": ig_acc.get("profile_picture_url"),
                        "message": f"Found linked Instagram @{ig_acc.get('username')} on Page '{page_data.get('name')}'",
                    }

            # 3. Auto-discovery via graph.instagram.com/me
            ig_me_resp = client.get(
                "https://graph.instagram.com/me",
                params={"fields": "id,username,name,profile_picture_url,account_type", "access_token": access_token},
            )
            ig_me_data = ig_me_resp.json()
            if ig_me_resp.status_code == 200 and "username" in ig_me_data:
                return {
                    "success": True,
                    "account_id": str(ig_me_data.get("id")),
                    "username": ig_me_data.get("username"),
                    "name": ig_me_data.get("name") or ig_me_data.get("username"),
                    "profile_picture_url": ig_me_data.get("profile_picture_url"),
                    "message": f"Successfully connected to @{ig_me_data.get('username')}",
                }

            # 4. Auto-discovery via graph.facebook.com/me/accounts
            me_accounts_url = f"{GRAPH_API_BASE}/me/accounts"
            me_resp = client.get(
                me_accounts_url,
                params={"fields": "id,name,instagram_business_account{id,username,name,profile_picture_url}"},
                headers=headers,
            )
            me_data = me_resp.json()

            if me_resp.status_code == 200 and "data" in me_data:
                for page in me_data.get("data", []):
                    if "instagram_business_account" in page:
                        ig_acc = page["instagram_business_account"]
                        return {
                            "success": True,
                            "account_id": str(ig_acc.get("id")),
                            "username": ig_acc.get("username"),
                            "name": ig_acc.get("name") or ig_acc.get("username"),
                            "profile_picture_url": ig_acc.get("profile_picture_url"),
                            "message": f"Auto-discovered Instagram @{ig_acc.get('username')} via Facebook Page '{page.get('name')}'",
                        }

            # 5. Check /me to see token validity
            me_check = client.get(f"{GRAPH_API_BASE}/me", params={"fields": "id,name"}, headers=headers)
            me_check_data = me_check.json()
            if me_check.status_code == 200:
                user_name = me_check_data.get("name", "User")
                return {
                    "success": False,
                    "message": f"Token valid for '{user_name}', but no Instagram Business Account is linked to your Facebook Pages.",
                }
            else:
                err_msg = me_check_data.get("error", {}).get("message", "Invalid OAuth access token.")
                return {
                    "success": False,
                    "message": f"Instagram API error: {err_msg}",
                }
    except Exception as exc:
        logger.warning("Error testing Instagram connection: %s", exc)
        return {
            "success": False,
            "message": f"Connection failed: {str(exc)}",
        }


def create_reels_container(
    account_id: str,
    access_token: str,
    caption: str,
    video_path: Optional[str] = None,
    video_url: Optional[str] = None,
) -> dict:
    """
    Step 1: Create an Instagram Reel container on Meta Graph API.
    Uses resumable upload if local video_path is provided.
    """
    url = f"{GRAPH_API_BASE}/{account_id}/media"
    data = {
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true",
        "access_token": access_token,
    }

    if video_url:
        data["video_url"] = video_url
    else:
        data["upload_type"] = "resumable"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, data=data)
        res_data = resp.json()

        if resp.status_code != 200 or "id" not in res_data:
            err_msg = res_data.get("error", {}).get("message", resp.text)
            raise RuntimeError(f"Failed to create Instagram Reels container: {err_msg}")

        return res_data


def upload_video_resumable(upload_uri: str, access_token: str, video_path: str) -> None:
    """
    Step 1b: Upload video bytes directly to Meta rupload endpoint for local files.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    file_size = os.path.getsize(video_path)
    headers = {
        "Authorization": f"OAuth {access_token}",
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream",
    }

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(upload_uri, headers=headers, content=video_bytes)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to upload video chunks to Instagram: {resp.text}")


def wait_for_container_ready(
    container_id: str,
    access_token: str,
    max_wait_seconds: int = 180,
    poll_interval: int = 5,
) -> bool:
    """
    Step 2: Poll container until Instagram finishes transcoding the video (status_code == 'FINISHED').
    """
    url = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": access_token,
    }

    start_time = time.time()
    with httpx.Client(timeout=15.0) as client:
        while time.time() - start_time < max_wait_seconds:
            resp = client.get(url, params=params)
            data = resp.json()
            status_code = data.get("status_code", "").upper()

            if status_code == "FINISHED":
                logger.info("Instagram container %s processing finished.", container_id)
                return True
            elif status_code in ("ERROR", "EXPIRED"):
                err_msg = data.get("status", f"Container failed with status: {status_code}")
                raise RuntimeError(f"Instagram media processing error: {err_msg}")

            logger.debug("Instagram container %s status: %s. Waiting %ds...", container_id, status_code, poll_interval)
            time.sleep(poll_interval)

    raise TimeoutError(f"Instagram container {container_id} processing timed out after {max_wait_seconds}s.")


def publish_container(account_id: str, access_token: str, container_id: str) -> str:
    """
    Step 3: Publish the ready container to Instagram Reels.
    Returns published media ID.
    """
    url = f"{GRAPH_API_BASE}/{account_id}/media_publish"
    data = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, data=data)
        res_data = resp.json()

        if resp.status_code != 200 or "id" not in res_data:
            err_msg = res_data.get("error", {}).get("message", resp.text)
            raise RuntimeError(f"Failed to publish Instagram Reel: {err_msg}")

        return res_data["id"]


def fetch_media_permalink(media_id: str, access_token: str) -> Optional[str]:
    """
    Fetch direct URL to the published Instagram Reel (e.g. https://www.instagram.com/reel/...).
    """
    url = f"{GRAPH_API_BASE}/{media_id}"
    params = {
        "fields": "id,permalink",
        "access_token": access_token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            return data.get("permalink")
    except Exception as exc:
        logger.warning("Could not fetch permalink for Instagram media %s: %s", media_id, exc)
        return None


def publish_reel_for_post(post: Post, db: Session) -> dict:
    """
    End-to-end publishing pipeline for Instagram Reels:
    1. Check if channel has Instagram enabled and valid credentials.
    2. Build caption and format hashtags.
    3. Upload video and poll container.
    4. Publish Reel and record permalink on post.
    """
    # Find channel config
    ch = db.query(ChannelConfig).filter(ChannelConfig.key == post.channel).first()
    if not ch or not ch.instagram_enabled:
        return {
            "skipped": True,
            "reason": "Instagram publishing is not enabled for this channel.",
        }

    account_id = (ch.instagram_account_id or "").strip()
    access_token = (ch.instagram_access_token or "").strip()

    if not account_id or not access_token:
        err = "Instagram Account ID or Access Token is missing in Channel Config."
        post.instagram_status = "failed"
        post.instagram_error = err
        db.commit()
        return {"success": False, "error": err}

    video_path = post.clean_video_path or post.video_path
    if not video_path or not os.path.exists(video_path):
        err = f"Video file not found for post {post.id}: {video_path}"
        post.instagram_status = "failed"
        post.instagram_error = err
        db.commit()
        return {"success": False, "error": err}

    caption = format_instagram_caption(
        title=post.enriched_title or post.title or "",
        description=post.enriched_description or post.description or "",
        tags=post.enriched_tags or post.tags or "",
    )

    try:
        post.instagram_status = "pending"
        post.instagram_error = None
        db.commit()

        # Step 1: Create container
        container_data = create_reels_container(
            account_id=account_id,
            access_token=access_token,
            caption=caption,
            video_path=video_path,
        )
        container_id = container_data["id"]
        upload_uri = container_data.get("uri")

        # Step 1b: Upload video binary if resumable upload uri provided
        if upload_uri:
            upload_video_resumable(
                upload_uri=upload_uri,
                access_token=access_token,
                video_path=video_path,
            )

        # Step 2: Poll container status
        wait_for_container_ready(container_id=container_id, access_token=access_token)

        # Step 3: Publish Reel
        media_id = publish_container(
            account_id=account_id,
            access_token=access_token,
            container_id=container_id,
        )

        # Step 4: Fetch permalink
        permalink = fetch_media_permalink(media_id=media_id, access_token=access_token) or f"https://www.instagram.com/reel/{media_id}/"

        # Update Post record
        post.instagram_media_id = media_id
        post.instagram_post_url = permalink
        post.instagram_status = "published"
        post.instagram_error = None
        db.commit()

        logger.info("Successfully published Reel for Post %s: %s", post.id, permalink)
        return {
            "success": True,
            "media_id": media_id,
            "permalink": permalink,
        }
    except Exception as exc:
        logger.error("Failed to publish Instagram Reel for Post %s: %s", post.id, exc)
        post.instagram_status = "failed"
        post.instagram_error = str(exc)
        db.commit()
        return {
            "success": False,
            "error": str(exc),
        }


# Backwards-compatible alias
test_instagram_connection = verify_instagram_credentials


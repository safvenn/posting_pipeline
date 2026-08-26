"""
Watermark removal service — SSH + gwr (Gemini Watermark Remover).

Exact port of the n8n workflow nodes:
  1. SFTP: upload input video → worker /tmp/gemini-watermark-remover/input-{id}.mp4
  2. SSH: cd /home/ubuntu/video-worker && pnpm exec gwr remove input.mp4 --output clean.mp4 --video-bitrate-mbps 30 --json
  3. Parse gwr JSON stdout — check exit code AND JSON success field
  4. SFTP: download clean-{id}.mp4 → local processed/
  5. SSH: rm -f input-{id}.mp4 clean-{id}.mp4   (worker cleanup)
  6. Delete local original upload (disk hygiene)

CRITICAL: Always check exit code before proceeding — this was the original bug.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# SSH helpers                                                                   #
# --------------------------------------------------------------------------- #

def _ssh_client() -> paramiko.SSHClient:
    """Open an authenticated SSH connection to the worker."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_path = os.path.expanduser(settings.worker_ssh_key_path) if settings.worker_ssh_key_path else ""

    connect_kwargs = {
        "hostname": settings.worker_ssh_host,
        "port": settings.worker_ssh_port,
        "username": settings.worker_ssh_user,
        "timeout": 30,
    }
    if key_path and os.path.exists(key_path):
        connect_kwargs["key_filename"] = key_path
    if settings.worker_ssh_password:
        connect_kwargs["password"] = settings.worker_ssh_password

    client.connect(**connect_kwargs)
    return client


def _ssh_exec(client: paramiko.SSHClient, command: str, timeout: int = 300) -> tuple[int, str, str]:
    """
    Execute a command on the worker.
    Returns (exit_code, stdout, stderr).
    Always returns the real exit code — never swallows failures.
    """
    logger.debug("SSH exec: %s", command)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return exit_code, out, err


# --------------------------------------------------------------------------- #
# Status helper                                                                 #
# --------------------------------------------------------------------------- #

def _set_status(db, post: Post, status: str, error: str | None = None) -> None:
    post.status = status
    post.error_message = error
    post.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Post %s -> %s", post.id, status)


# --------------------------------------------------------------------------- #
# Active Jobs & Cancellation Tracker                                         #
# --------------------------------------------------------------------------- #

_active_jobs: dict[int, dict] = {}


def cancel_cleaning_job(post_id: int) -> None:
    """
    Cancel any active watermark removal for post_id.
    Immediately kills remote processes (gwr, node, chromium) on the AWS EC2 worker
    and deletes all remote input/output files from the AWS worker SSD.
    """
    job_info = _active_jobs.get(post_id)
    if job_info:
        job_info["cancelled"] = True
        logger.info("Cancelling active watermark removal for post %s (job=%s)", post_id, job_info.get("job_id"))
        active_ssh = job_info.get("ssh_client")
        if active_ssh:
            try:
                active_ssh.close()
            except Exception:
                pass

    # Connect to AWS EC2 worker and terminate processes + delete temp files
    try:
        client = _ssh_client()
        tmp_dir = settings.gwr_tmp_dir
        cmd = (
            f"pkill -9 -f 'input-{post_id}-' 2>/dev/null || true; "
            f"pkill -9 -f 'clean-{post_id}-' 2>/dev/null || true; "
            f"pkill -9 -f 'gwr.*{post_id}' 2>/dev/null || true; "
            f"rm -rf {tmp_dir}/input-{post_id}-* {tmp_dir}/clean-{post_id}-* {tmp_dir}/*{post_id}* /tmp/gemini-watermark-remover/*{post_id}* /tmp/*{post_id}* 2>/dev/null || true"
        )
        logger.info("Executing immediate worker process kill and AWS file deletion for post %s", post_id)
        _ssh_exec(client, cmd, timeout=15)
        client.close()
        logger.info("AWS worker process killed and remote files deleted for post %s", post_id)
    except Exception as exc:
        logger.warning("Could not execute remote kill/cleanup for post %s: %s", post_id, exc)
    finally:
        _active_jobs.pop(post_id, None)


# --------------------------------------------------------------------------- #
# Main removal pipeline                                                         #
# --------------------------------------------------------------------------- #

def remove_watermark(post_id: int) -> None:
    """
    Full gwr watermark removal pipeline.
    Status: queued -> cleaning -> cleaned (or -> failed)
    Runs in a background thread per post.
    """
    db = SessionLocal()
    ssh: paramiko.SSHClient | None = None
    local_clean_path: Path | None = None
    job_id = f"{post_id}-{uuid.uuid4().hex[:8]}"
    remote_input = f"{settings.gwr_tmp_dir}/input-{job_id}.mp4"
    remote_clean = f"{settings.gwr_tmp_dir}/clean-{job_id}.mp4"

    try:
        post = db.get(Post, post_id)
        if not post:
            logger.error("remove_watermark: unknown post_id=%s", post_id)
            return

        if post.status != "queued":
            logger.warning("Post %s not queued (status=%s), skip", post_id, post.status)
            return

        _set_status(db, post, "cleaning")

        # Validate config
        if not settings.worker_ssh_host:
            raise RuntimeError(
                "WORKER_SSH_HOST not configured. Set it in .env before using gwr removal."
            )

        input_path = Path(post.video_path)
        if not input_path.exists():
            _set_status(db, post, "failed", f"Input file not found: {input_path}")
            return

        local_clean_path = settings.processed_path() / f"clean-{job_id}.mp4"

        # Register active job
        _active_jobs[post_id] = {
            "job_id": job_id,
            "remote_input": remote_input,
            "remote_clean": remote_clean,
            "cancelled": False,
        }

        # ---- Open SSH ----
        logger.info("Connecting to worker %s:%s", settings.worker_ssh_host, settings.worker_ssh_port)
        ssh = _ssh_client()
        if post_id in _active_jobs:
            _active_jobs[post_id]["ssh_client"] = ssh
        sftp = ssh.open_sftp()

        # ---- Ensure remote tmp dir exists and prune stale files ----
        _ssh_exec(ssh, f"mkdir -p {settings.gwr_tmp_dir} && find {settings.gwr_tmp_dir} -type f -mmin +30 -delete 2>/dev/null || true")

        # Check if cancelled
        if _active_jobs.get(post_id, {}).get("cancelled"):
            logger.info("Post %s cancelled before upload, aborting", post_id)
            return

        # ---- Step 1: Upload video to worker ----
        logger.info("Post %s: SFTP upload → %s", post_id, remote_input)
        sftp.put(str(input_path), remote_input)

        # Check if cancelled
        if _active_jobs.get(post_id, {}).get("cancelled"):
            logger.info("Post %s cancelled after upload, aborting", post_id)
            return

        # ---- Step 2: Run gwr remove ----
        gwr_cmd = (
            f"cd {settings.gwr_worker_dir} && "
            f"pnpm exec gwr remove {remote_input} "
            f"--output {remote_clean} "
            f"--video-bitrate-mbps {settings.gwr_video_bitrate_mbps} "
            f"--json"
        )
        logger.info("Post %s: running gwr", post_id)
        start = time.monotonic()
        code, stdout, stderr = _ssh_exec(ssh, gwr_cmd, timeout=1800)  # 30 min max
        elapsed = time.monotonic() - start

        # Check if cancelled
        if _active_jobs.get(post_id, {}).get("cancelled"):
            logger.info("Post %s was cancelled during gwr, aborting", post_id)
            return

        # CRITICAL: check exit code — never silently continue on failure
        if code != 0:
            gwr_err = _parse_gwr_error(stdout, stderr)
            raise RuntimeError(
                f"gwr exited {code} after {elapsed:.1f}s: {gwr_err}"
            )

        # Parse gwr JSON output to confirm success
        _check_gwr_json(stdout, post_id)
        logger.info("Post %s: gwr done in %.1fs", post_id, elapsed)

        # ---- Step 3: Download clean video ----
        logger.info("Post %s: SFTP download ← %s", post_id, remote_clean)
        sftp.get(remote_clean, str(local_clean_path))
        sftp.close()

        # Verify downloaded file is non-empty
        if not local_clean_path.exists() or local_clean_path.stat().st_size == 0:
            raise RuntimeError(f"Downloaded clean video is empty: {local_clean_path}")

        # ---- Step 4: Cleanup remote files ----
        code, _, err = _ssh_exec(ssh, f"rm -f {remote_input} {remote_clean}")
        if code != 0:
            logger.warning("Post %s: remote cleanup failed (non-fatal): %s", post_id, err)
        else:
            logger.debug("Post %s: remote files cleaned up", post_id)

        # Update DB if post still exists
        current_post = db.get(Post, post_id)
        if current_post:
            current_post.clean_video_path = str(local_clean_path)
            _set_status(db, current_post, "cleaned")
            local_clean_path = None  # success — don't delete on exit
        else:
            logger.info("Post %s was deleted while cleaning completed, cleaning up local file", post_id)

    except paramiko.AuthenticationException as exc:
        err = f"SSH auth failed: {exc}"
        logger.error("Post %s: %s", post_id, err)
        if p := db.get(Post, post_id):
            _set_status(db, p, "failed", err)

    except paramiko.SSHException as exc:
        err = f"SSH error: {exc}"
        logger.error("Post %s: %s", post_id, err)
        if p := db.get(Post, post_id):
            _set_status(db, p, "failed", err)

    except Exception as exc:
        err = f"watermark removal error: {exc}"
        logger.exception("Post %s unexpected error", post_id)
        if p := db.get(Post, post_id):
            _set_status(db, p, "failed", err)

    finally:
        _active_jobs.pop(post_id, None)

        # Remote file cleanup on error
        if ssh and remote_input and remote_clean:
            try:
                _ssh_exec(ssh, f"rm -f {remote_input} {remote_clean}")
            except Exception:
                pass

        # Close SSH
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

        # Delete partial clean file if we failed
        if local_clean_path and local_clean_path.exists():
            try:
                local_clean_path.unlink()
                logger.debug("Deleted partial clean file %s", local_clean_path)
            except Exception:
                pass

        # Delete original upload after successful clean (disk hygiene)
        try:
            db2 = SessionLocal()
            p = db2.get(Post, post_id)
            if p and p.status == "cleaned" and p.video_path:
                orig = Path(p.video_path)
                if orig.exists():
                    orig.unlink()
                    logger.debug("Deleted original upload %s", orig)
            db2.close()
        except Exception:
            pass

        db.close()


def _parse_gwr_error(stdout: str, stderr: str) -> str:
    """Try to extract a meaningful error from gwr output."""
    # gwr outputs JSON — try to parse it
    for text in (stdout, stderr):
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict):
                return data.get("error", data.get("message", str(data)))[:500]
        except Exception:
            pass
    combined = (stderr or stdout or "no output").strip()
    return combined[-500:]  # last 500 chars of stderr


def _check_gwr_json(stdout: str, post_id: int) -> None:
    """
    Parse gwr --json output and raise if it signals failure.
    gwr outputs JSON like: {"success": true, "outputPath": "..."}
    """
    try:
        data = json.loads(stdout.strip())
        if isinstance(data, dict):
            if data.get("success") is False:
                raise RuntimeError(
                    f"gwr reported failure: {data.get('error', data)}"
                )
            # success — log output path
            logger.debug("Post %s: gwr output=%s", post_id, data.get("outputPath", "?"))
    except json.JSONDecodeError:
        # gwr may not always output clean JSON — if exit code was 0, treat as success
        logger.debug("Post %s: gwr stdout not JSON (exit 0, continuing): %.200s", post_id, stdout)

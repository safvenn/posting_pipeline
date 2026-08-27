"""
Video Quality & 1080p Full HD Enhancement Service.

Enforces YouTube master upload specifications:
- 1080p Full HD resolution (1080x1920 for 9:16 vertical Shorts, 1920x1080 for 16:9 horizontal)
- High-quality Lanczos resampling
- H.264 High Profile (Level 4.2), YUV 4:2:0 chroma subsampling
- Visually lossless CRF 17 with 25-35 Mbps bitrate limits
- BT.709 HD color primaries, transfer characteristics, and color space
- High fidelity 384 kbps 48 kHz AAC stereo audio
- Fast-start moov atom header for immediate streaming ingestion
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Cached binary paths
_FFMPEG_PATH: Optional[str] = None
_FFPROBE_PATH: Optional[str] = None


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg executable in environment or standard paths."""
    global _FFMPEG_PATH
    if _FFMPEG_PATH and os.path.exists(_FFMPEG_PATH):
        return _FFMPEG_PATH

    path = shutil.which("ffmpeg")
    if not path and os.name == "nt":
        # Search common Windows winget / scoop / local appdata locations
        candidates = [
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_root.exists():
                for found in winget_root.glob("**/ffmpeg.exe"):
                    candidates.append(str(found))

        for c in candidates:
            if os.path.exists(c):
                path = c
                break

    _FFMPEG_PATH = path
    return path


def find_ffprobe() -> Optional[str]:
    """Locate ffprobe executable in environment or standard paths."""
    global _FFPROBE_PATH
    if _FFPROBE_PATH and os.path.exists(_FFPROBE_PATH):
        return _FFPROBE_PATH

    path = shutil.which("ffprobe")
    if not path and os.name == "nt":
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            sibling = Path(ffmpeg).parent / "ffprobe.exe"
            if sibling.exists():
                path = str(sibling)

    _FFPROBE_PATH = path
    return path


def get_video_metadata(video_path: str | Path) -> dict[str, Any]:
    """
    Extract video resolution, codec, duration, bitrate, and aspect ratio.
    Returns a dictionary with width, height, duration, is_vertical, etc.
    """
    path_str = str(video_path)
    info: dict[str, Any] = {
        "width": 0,
        "height": 0,
        "duration": 0.0,
        "codec": "",
        "bitrate": 0,
        "is_vertical": True,
        "fps": 30.0,
    }

    if not os.path.exists(path_str):
        return info

    ffprobe = find_ffprobe()
    if not ffprobe:
        return info

    try:
        cmd = [
            ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            path_str,
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            for s in streams:
                if s.get("codec_type") == "video":
                    w = int(s.get("width") or 0)
                    h = int(s.get("height") or 0)
                    # Check rotation metadata
                    tags = s.get("tags") or {}
                    rotate = tags.get("rotate", "0")
                    if rotate in ("90", "270"):
                        w, h = h, w

                    info["width"] = w
                    info["height"] = h
                    info["codec"] = s.get("codec_name", "")
                    info["is_vertical"] = h > w if (w > 0 and h > 0) else True

                    # Extract frame rate
                    r_frame_rate = s.get("r_frame_rate", "30/1")
                    if "/" in r_frame_rate:
                        num, den = r_frame_rate.split("/")
                        if den and float(den) > 0:
                            info["fps"] = round(float(num) / float(den), 2)
                    break

            fmt = data.get("format", {})
            info["duration"] = float(fmt.get("duration") or 0.0)
            info["bitrate"] = int(fmt.get("bit_rate") or 0)
    except Exception as exc:
        logger.warning("ffprobe inspection error on %s: %s", path_str, exc)

    return info


def calculate_1080p_dimensions(width: int, height: int) -> Tuple[int, int]:
    """
    Calculate target 1080p Full HD dimensions preserving aspect ratio:
    - Vertical (9:16 Shorts): Target width is 1080, height is 1920.
    - Horizontal (16:9 Standard): Target height is 1080, width is 1920.
    - Non-standard: Scales so minimum dimension is 1080 and both dimensions are even integers.
    """
    if width <= 0 or height <= 0:
        return 1080, 1920

    is_vertical = height > width

    if is_vertical:
        # Scale width to 1080, calculate proportional height
        target_w = 1080
        target_h = int(round(height * (1080.0 / width)))
        if target_h % 2 != 0:
            target_h += 1
        return target_w, target_h
    else:
        # Scale height to 1080, calculate proportional width
        target_h = 1080
        target_w = int(round(width * (1080.0 / height)))
        if target_w % 2 != 0:
            target_w += 1
        return target_w, target_h


def enhance_to_1080p_hd(
    input_path: str | Path,
    output_path: Optional[str | Path] = None,
    force: bool = False,
) -> str:
    """
    Enhance video to 1080p Full HD Master Quality for YouTube upload.

    Applies:
    - High-quality Lanczos scaling to 1080p
    - H.264 High Profile (Level 4.2), YUV420P
    - CRF 17 (visually lossless) with 25-35M bitrate
    - BT.709 color matrix tags (YouTube HD standard)
    - 384k 48kHz AAC stereo audio
    - +faststart moov atom header

    Returns the path to the enhanced 1080p video file (or original if ffmpeg is unavailable).
    """
    in_path = Path(input_path).resolve()
    if not in_path.exists():
        logger.warning("enhance_to_1080p_hd: Input file not found: %s", in_path)
        return str(input_path)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.warning("enhance_to_1080p_hd: FFmpeg binary not found on system. Proceeding with original video.")
        return str(in_path)

    # Determine output path
    if output_path:
        out_path = Path(output_path).resolve()
    else:
        # Generate companion 1080p filename
        stem = in_path.stem
        if stem.endswith("_1080p") or stem.endswith("-1080p"):
            out_path = in_path
        else:
            out_path = in_path.parent / f"{stem}_1080p.mp4"

    # Avoid re-encoding if output already exists, is fresh, and force is False
    if not force and out_path.exists() and out_path.stat().st_size > 0 and out_path != in_path:
        meta = get_video_metadata(out_path)
        if (meta.get("width") == 1080 or meta.get("height") == 1080) and meta.get("width", 0) >= 1080:
            logger.info("Existing 1080p enhanced video found: %s", out_path)
            return str(out_path)

    # Temporary intermediate target if in_path == out_path
    actual_target = out_path
    if in_path == out_path:
        actual_target = in_path.parent / f"tmp_1080p_{in_path.name}"

    # Build scaling filter with Lanczos interpolation and YUV420P format
    scale_filter = (
        "scale='if(gt(ih,iw),1080,-2)':'if(gt(ih,iw),-2,1080)':flags=lanczos,"
        "format=yuv420p"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(in_path),
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-crf", "17",
        "-b:v", "25M",
        "-maxrate", "35M",
        "-bufsize", "50M",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(actual_target),
    ]

    logger.info("Enhancing video to 1080p Full HD master quality: %s -> %s", in_path.name, actual_target.name)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            logger.warning(
                "FFmpeg 1080p enhancement returned non-zero code %d. Error: %s. Using original video.",
                proc.returncode,
                proc.stderr[-500:] if proc.stderr else "Unknown error",
            )
            if actual_target.exists() and actual_target != in_path:
                try:
                    actual_target.unlink()
                except Exception:
                    pass
            return str(in_path)

        if not actual_target.exists() or actual_target.stat().st_size == 0:
            logger.warning("1080p output file is missing or empty. Using original video.")
            return str(in_path)

        # If we used a temporary intermediate file, replace the destination
        if in_path == out_path:
            shutil.move(str(actual_target), str(out_path))

        logger.info(
            "1080p Full HD enhancement completed successfully: %s (size: %.2f MB)",
            out_path.name,
            out_path.stat().st_size / (1024 * 1024),
        )
        return str(out_path)

    except Exception as exc:
        logger.exception("1080p video enhancement failed for %s: %s", in_path, exc)
        return str(in_path)

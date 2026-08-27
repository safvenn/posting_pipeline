"""
Unit tests for Video Quality & 1080p Full HD Enhancement service.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.video_quality import (
    calculate_1080p_dimensions,
    enhance_to_1080p_hd,
    find_ffmpeg,
    find_ffprobe,
    get_video_metadata,
)


def test_find_ffmpeg_and_ffprobe():
    """Verify that find_ffmpeg and find_ffprobe return paths or None."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    # At least ffmpeg should be a string or None
    assert ffmpeg is None or isinstance(ffmpeg, str)
    assert ffprobe is None or isinstance(ffprobe, str)


def test_calculate_1080p_dimensions_vertical():
    """Verify vertical video dimensions scale width to 1080."""
    # 720x1280 (9:16 Shorts) -> 1080x1920
    w, h = calculate_1080p_dimensions(720, 1280)
    assert w == 1080
    assert h == 1920
    assert w % 2 == 0
    assert h % 2 == 0

    # 1080x1920 -> 1080x1920
    w, h = calculate_1080p_dimensions(1080, 1920)
    assert w == 1080
    assert h == 1920

    # 540x960 -> 1080x1920
    w, h = calculate_1080p_dimensions(540, 960)
    assert w == 1080
    assert h == 1920


def test_calculate_1080p_dimensions_horizontal():
    """Verify horizontal video dimensions scale height to 1080."""
    # 1280x720 (16:9 Standard) -> 1920x1080
    w, h = calculate_1080p_dimensions(1280, 720)
    assert w == 1920
    assert h == 1080
    assert w % 2 == 0
    assert h % 2 == 0

    # 1920x1080 -> 1920x1080
    w, h = calculate_1080p_dimensions(1920, 1080)
    assert w == 1920
    assert h == 1080


def test_calculate_1080p_dimensions_edge_cases():
    """Verify fallback and odd dimensions."""
    # Non-standard 721x1281 -> ensures even integers
    w, h = calculate_1080p_dimensions(721, 1281)
    assert w == 1080
    assert h % 2 == 0

    # 0 or negative
    w, h = calculate_1080p_dimensions(0, 0)
    assert w == 1080
    assert h == 1920


def test_get_video_metadata_nonexistent_file():
    """Metadata extraction on missing file returns default dictionary."""
    meta = get_video_metadata("non_existent_file_xyz_123.mp4")
    assert meta["width"] == 0
    assert meta["height"] == 0
    assert meta["duration"] == 0.0


@patch("backend.services.video_quality.find_ffprobe")
@patch("subprocess.run")
def test_get_video_metadata_mocked(mock_run, mock_find_ffprobe):
    """Test ffprobe output parsing with mock."""
    mock_find_ffprobe.return_value = "ffprobe"
    fake_ffprobe_json = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "60/1",
            }
        ],
        "format": {
            "duration": "45.5",
            "bit_rate": "15000000",
        },
    }
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(fake_ffprobe_json)
    mock_run.return_value = mock_proc

    with patch("os.path.exists", return_value=True):
        meta = get_video_metadata("sample.mp4")

    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["codec"] == "h264"
    assert meta["fps"] == 60.0
    assert meta["duration"] == 45.5
    assert meta["bitrate"] == 15000000
    assert meta["is_vertical"] is True


def test_enhance_to_1080p_hd_missing_file():
    """Enhance returns original path if input does not exist."""
    res = enhance_to_1080p_hd("non_existent_file.mp4")
    assert "non_existent_file.mp4" in res


@patch("backend.services.video_quality.find_ffmpeg")
@patch("subprocess.run")
def test_enhance_to_1080p_hd_command_construction(mock_run, mock_find_ffmpeg, tmp_path):
    """Verify FFmpeg command contains all required YouTube 1080p master quality flags."""
    mock_find_ffmpeg.return_value = "ffmpeg"
    fake_input = tmp_path / "input.mp4"
    fake_input.write_bytes(b"dummy video data")

    fake_output = tmp_path / "output_1080p.mp4"

    def fake_subprocess(cmd, **kwargs):
        fake_output.write_bytes(b"enhanced 1080p video data")
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    mock_run.side_effect = fake_subprocess

    result = enhance_to_1080p_hd(fake_input, fake_output)
    assert result == str(fake_output.resolve())

    # Verify subprocess called with proper ffmpeg arguments
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]

    assert called_cmd[0] == "ffmpeg"
    assert "-i" in called_cmd
    assert "-vf" in called_cmd
    assert "-c:v" in called_cmd
    assert "libx264" in called_cmd
    assert "-profile:v" in called_cmd
    assert "high" in called_cmd
    assert "-level:v" in called_cmd
    assert "4.2" in called_cmd
    assert "-crf" in called_cmd
    assert "17" in called_cmd
    assert "-colorspace" in called_cmd
    assert "bt709" in called_cmd
    assert "-color_primaries" in called_cmd
    assert "bt709" in called_cmd
    assert "-c:a" in called_cmd
    assert "aac" in called_cmd
    assert "-b:a" in called_cmd
    assert "384k" in called_cmd
    assert "-ar" in called_cmd
    assert "48000" in called_cmd
    assert "-movflags" in called_cmd
    assert "+faststart" in called_cmd


@patch("backend.services.video_quality.find_ffmpeg")
@patch("subprocess.run")
def test_enhance_to_1080p_hd_ffmpeg_failure_fallback(mock_run, mock_find_ffmpeg, tmp_path):
    """If FFmpeg returns non-zero, it safely falls back to original video."""
    mock_find_ffmpeg.return_value = "ffmpeg"
    fake_input = tmp_path / "input.mp4"
    fake_input.write_bytes(b"dummy video data")

    proc = MagicMock()
    proc.returncode = 1
    proc.stderr = "FFmpeg error: corrupt stream"
    mock_run.return_value = proc

    result = enhance_to_1080p_hd(fake_input)
    assert result == str(fake_input.resolve())

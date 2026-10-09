import pytest
import subprocess
from pathlib import Path
from app.services.template_cache import normalize_template_video
from app.services.audio_extractor import probe_video
from app.services.loop_renderer import fast_mux_loop_video

@pytest.fixture
def temp_workspace(tmp_path):
    bg_path = tmp_path / "dummy_bg.mp4"
    audio_path = tmp_path / "dummy_audio.m4a"
    logo_path = tmp_path / "dummy_logo.png"
    
    # 1 second green background in HEVC
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=1080x1920:d=1",
        "-c:v", "libx265", str(bg_path)
    ], check=True, stderr=subprocess.DEVNULL)
    
    # 5 seconds sine wave in AAC
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=5",
        "-c:a", "aac", str(audio_path)
    ], check=True, stderr=subprocess.DEVNULL)
    
    # Dummy logo
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=white:s=100x100:d=0.1",
        "-frames:v", "1", str(logo_path)
    ], check=True, stderr=subprocess.DEVNULL)
    
    yield tmp_path, bg_path, audio_path, logo_path

@pytest.mark.asyncio
async def test_fast_mux_process(temp_workspace):
    tmp_path, bg_path, audio_path, logo_path = temp_workspace
    
    # 1. Optimize template
    out_cache_dir = tmp_path / "cache"
    out_cache_dir.mkdir(exist_ok=True)
    optimized_path = out_cache_dir / "optimized.mp4"
    
    normalize_template_video(
        input_path=bg_path,
        output_path=optimized_path,
        orientation="portrait",
        logo_path=logo_path
    )
    
    assert optimized_path.exists()
    info = probe_video(optimized_path)
    assert info["video_codec"] == "h264"
    
    # 2. Fast Mux
    final_output = tmp_path / "final.mp4"
    fast_mux_loop_video(
        normalized_video=optimized_path,
        audio=audio_path,
        output=final_output,
        duration=5.0
    )
    
    assert final_output.exists()
    
    # Verify final output duration matches audio exactly
    final_info = probe_video(final_output)
    assert final_info["video_codec"] == "h264"
    assert abs(final_info["duration"] - 5.0) < 0.1
    
    # Verify no stream errors by running a full decode test
    res = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(final_output), "-f", "null", "-"
    ], capture_output=True, text=True)
    assert res.returncode == 0
    assert res.stderr.strip() == "", f"FFmpeg validation failed: {res.stderr}"


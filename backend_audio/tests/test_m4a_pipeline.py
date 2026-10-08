"""M4A pipeline: stream-copy AAC, transcode fallback, integrity, no MP3."""

import subprocess

import pytest

from app.services import audio_extractor as ae


def _make_mp4(path, audio="aac", duration=4, with_audio=True):
    if with_audio:
        if audio == "aac":
            a = ["-f", "lavfi", "-i", f"sine=frequency=440:d={duration}",
                 "-c:a", "aac"]
        elif audio == "pcm":
            a = ["-f", "lavfi", "-i", f"sine=frequency=440:d={duration}",
                 "-c:a", "pcm_s16le"]
        else:
            raise ValueError(audio)
    else:
        a = []
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=blue:s=320x240:d={duration}",
           *a, "-c:v", "libx264", "-shortest", str(path)]
    subprocess.run(cmd, check=True, timeout=120, capture_output=True)
    return path


def test_aac_stream_copy_preserves_codec(tmp_path):
    src = _make_mp4(tmp_path / "src.mp4", audio="aac")
    before = ae.probe_media(src)
    out = ae.extract_audio(src, tmp_path / "audio.m4a")
    after = ae.probe_media(out)
    assert after["audio_codec"] == "aac"
    assert abs(after["duration"] - before["duration"]) < 0.5
    assert out.stat().st_size > 0
    assert out.suffix == ".m4a"


def test_non_aac_falls_back_to_aac_transcode(tmp_path):
    src = _make_mp4(tmp_path / "src.mov", audio="pcm")
    out = ae.extract_audio(src, tmp_path / "audio.m4a")
    after = ae.probe_media(out)
    assert after["audio_codec"] == "aac"
    assert after["duration"] > 0


def test_missing_audio_is_source_audio_missing(tmp_path):
    src = _make_mp4(tmp_path / "silent.mp4", with_audio=False)
    with pytest.raises(ae.AudioError) as exc:
        ae.extract_audio(src, tmp_path / "audio.m4a")
    assert exc.value.code == "SOURCE_AUDIO_MISSING"


def test_corrupt_file_fails_loud(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video" * 100)
    with pytest.raises(ae.AudioError):
        ae.extract_audio(bad, tmp_path / "audio.m4a")


def test_rejects_non_m4a_dest(tmp_path):
    src = _make_mp4(tmp_path / "src.mp4", audio="aac")
    with pytest.raises(ae.AudioError) as exc:
        ae.extract_audio(src, tmp_path / "audio.mp3")
    assert exc.value.code == "BAD_DEST_FORMAT"


def test_no_mp3_in_default_pipeline():
    import pathlib

    for path in (pathlib.Path("app")).rglob("*.py"):
        text = path.read_text()
        assert "libmp3lame" not in text, path
        assert ".mp3" not in text, path


def test_render_accepts_m4a(tmp_path):
    from app.services import loop_renderer

    src = _make_mp4(tmp_path / "src.mp4", audio="aac", duration=6)
    m4a = ae.extract_audio(src, tmp_path / "audio.m4a")
    bg = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=320x240:d=3",
         "-c:v", "libx264", str(bg)],
        check=True, timeout=120, capture_output=True)
    dur = ae.probe_media(m4a)["duration"]
    out = tmp_path / "out.mp4"
    loop_renderer.build_loop_video(background=bg, audio=m4a, output=out,
                                   duration=dur, threads=1)
    got = ae.probe_media(out)
    assert abs(got["duration"] - dur) < 1.0
    assert got["audio_codec"] == "aac"

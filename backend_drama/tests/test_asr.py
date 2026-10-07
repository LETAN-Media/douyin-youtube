"""JianYing ASR result handling: SRT validation + Turso persistence.

Unit-level only (no network, no real ASR). The live acceptance result
(real Episode 1 -> 59 cues -> Turso) is recorded separately, never mocked.
"""

import re

import pytest

from app.db.repositories import asr as asr_repo


def _parse_srt(raw: str):
    """Mirror of the acceptance validator: returns cue list or raises."""
    blocks = re.split(r"\n\s*\n", raw.strip())
    if not blocks or not blocks[0].strip():
        raise ValueError("empty SRT")

    def _ts(s: str) -> int:
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)", s)
        if not m:
            raise ValueError(f"bad timestamp: {s[:40]}")
        h, mi, se, ms = map(int, m.groups())
        return ((h * 60 + mi) * 60 + se) * 1000 + ms

    cues = []
    for b in blocks:
        lines = b.strip().splitlines()
        if not lines[0].strip().isdigit():
            raise ValueError("bad cue index")
        m = re.match(r"(.+) --> (.+)", lines[1] if len(lines) > 1 else "")
        if not m:
            raise ValueError("bad cue timing")
        s, e = _ts(m.group(1)), _ts(m.group(2))
        if not s < e:
            raise ValueError("start >= end")
        if len(lines) < 3 or not any(line.strip() for line in lines[2:]):
            raise ValueError("empty cue text")
        cues.append((s, e))
    for i in range(len(cues) - 1):
        if not cues[i][0] < cues[i + 1][0]:
            raise ValueError("cues not ascending")
    return cues


GOOD_SRT = """1
00:00:00,320 --> 00:00:02,600
with every rise and fall of the waves

2
00:00:13,560 --> 00:00:14,680
my husband's father

3
00:02:55,760 --> 00:02:58,040
the end is near
"""


def test_srt_parser_valid():
    cues = _parse_srt(GOOD_SRT)
    assert len(cues) == 3
    assert cues[0] == (320, 2600)
    assert cues[-1] == (175760, 178040)


def test_srt_parser_empty():
    with pytest.raises(ValueError):
        _parse_srt("")
    with pytest.raises(ValueError):
        _parse_srt("   \n  \n")


def test_srt_parser_invalid_timestamps():
    bad_ts = GOOD_SRT.replace("00:00:13,560 --> 00:00:14,680", "13.56 --> 14.68")
    with pytest.raises(ValueError):
        _parse_srt(bad_ts)


def test_srt_parser_start_after_end():
    bad = GOOD_SRT.replace("00:00:13,560 --> 00:00:14,680", "00:00:14,680 --> 00:00:13,560")
    with pytest.raises(ValueError):
        _parse_srt(bad)


def test_srt_parser_not_ascending():
    swapped = "\n\n".join([
        GOOD_SRT.split("\n\n")[1],
        GOOD_SRT.split("\n\n")[0],
        GOOD_SRT.split("\n\n")[2],
    ])
    with pytest.raises(ValueError):
        _parse_srt(swapped)


def test_asr_row_lifecycle(db):
    row = asr_repo.start_asr("dep_test1", "dser_test1")
    assert row["status"] == "processing"
    assert row["attempt_count"] == 1
    done = asr_repo.complete_asr(
        "dep_test1", source_language="en", srt_text=GOOD_SRT,
        segment_count=3, duration_ms=178040,
    )
    assert done["status"] == "completed"
    assert done["segment_count"] == 3
    assert done["srt_text"] == GOOD_SRT
    back = asr_repo.get_asr("dep_test1")
    assert back is not None and back["status"] == "completed"
    assert back["srt_text"] == GOOD_SRT


def test_asr_failure_typed(db):
    row = asr_repo.fail_asr("dep_test2", "dser_test2", code="JIANYING_TIMEOUT",
                            message="exceeded")
    assert row["status"] == "failed"
    assert row["last_error_code"] == "JIANYING_TIMEOUT"
    assert asr_repo.get_asr("dep_missing") is None


def test_asr_completed_reload_after_cleanup(db, tmp_path):
    asr_repo.start_asr("dep_test3", "dser_test3")
    row = asr_repo.complete_asr(
        "dep_test3", source_language="en", srt_text=GOOD_SRT,
        segment_count=3, duration_ms=178040,
    )
    assert row["status"] == "completed"
    # Simulate temp cleanup: no file assertions here, only DB durability.
    back = asr_repo.get_asr("dep_test3")
    assert back is not None and len(back["srt_text"] or "") > 0
    assert back["segment_count"] == 3

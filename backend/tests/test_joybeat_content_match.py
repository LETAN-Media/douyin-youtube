import pytest
from unittest.mock import patch, MagicMock
from app.ai_metadata import (
    evaluate_content_match,
    clean_hashtag,
    generate_metadata_structured,
)
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline
from app.worker import validate_hashtags
from app.scheduler import pick_video, _try_pick_video


def test_evaluate_content_match_dance_keywords():
    # Video with dance keywords should pass
    caption = "今天上海练舞，超帅编舞翻跳 #街舞 #dance"
    matched, reason = evaluate_content_match(
        caption,
        niche="Male dance performance, choreography, dance covers",
        prompt_override="CONTENT SELECTION: Prioritize dance, choreography, dance covers."
    )
    assert matched is True
    assert "dance" in reason.lower() or "matched" in reason.lower()


def test_evaluate_content_match_rejects_fitness_body():
    # Video with pure fitness/shirtless/gym should fail
    caption = "在健身房举铁 秀身材腹肌脱衣 #健身 #肌肉男"
    matched, reason = evaluate_content_match(
        caption,
        niche="Male dance performance, choreography, dance covers",
        prompt_override="CONTENT SELECTION: Reject pure gym/body showcase, shirtless posing with no dance."
    )
    assert matched is False
    assert "CONTENT_MISMATCH" in reason


def test_clean_hashtag_blocks_joybeat_danielxu():
    # Disallows #joybeat and #danielxu
    assert clean_hashtag("#joybeat") == ""
    assert clean_hashtag("#danielxu") == ""
    assert clean_hashtag("#danniu") == ""
    assert clean_hashtag("#dance") == "#dance"
    assert clean_hashtag("#choreography") == "#choreography"


def test_validate_hashtags_for_joybeat_destination():
    dest = Destination(
        id="test-dest",
        name="JoyBeat Dance",
        fixed_hashtags=["#dance", "#choreography"],
        adaptive_hashtags=["#dancecover", "#dancer", "#urbandance"],
    )

    # Valid: contains 5 tags, includes fixed tags and adaptive
    valid_text = "Amazing choreography in Shanghai\n\n#dance #choreography #dancecover #dancer #urbandance"
    assert validate_hashtags(valid_text, destination=dest) is True

    # Invalid: includes #joybeat
    has_joybeat = "Amazing moves\n\n#dance #choreography #dancecover #joybeat #urbandance"
    assert validate_hashtags(has_joybeat, destination=dest) is False

    # Invalid: missing fixed hashtag
    missing_fixed = "Amazing moves\n\n#dance #dancevideo #dancecover #dancer #urbandance"
    assert validate_hashtags(missing_fixed, destination=dest) is False


def test_scheduler_pick_video_guardrail(db_session=None):
    # Mock DB session for testing pick_video filtering
    mock_db = MagicMock()
    pipeline = Pipeline(
        id="pipe-dance",
        name="JoyBeat Dance",
        niche="Male dance performance, choreography",
    )
    destination = Destination(
        id="dest-dance",
        name="JoyBeat Dance",
        metadata_profile="Male dance performance, choreography",
        prompt_override="CONTENT SELECTION: Prioritize dance, reject pure gym/body showcase. If not primarily dance mark as CONTENT_MISMATCH.",
    )
    source = DouyinSource(id="src-1", pipeline_id=pipeline.id, enabled=True)

    # Candidate 1: fitness body showcase (should be rejected and marked content_mismatch)
    v1 = DouyinVideo(
        id="v1",
        video_id="111",
        source_id="src-1",
        pipeline_id=pipeline.id,
        title="健身房举铁脱衣秀腹肌",
        description="纯身材展示",
        status="new",
        is_backlog=False,
    )
    # Candidate 2: dance choreography (should be accepted)
    v2 = DouyinVideo(
        id="v2",
        video_id="222",
        source_id="src-1",
        pipeline_id=pipeline.id,
        title="街舞大师超炸编舞翻跳",
        description="上海练舞室 choreography practice",
        status="new",
        is_backlog=False,
    )

    mock_db.execute.return_value.scalars.return_value.all.side_effect = [
        [source],      # sources query
        [v1, v2],      # candidates query
    ]

    picked = pick_video(mock_db, pipeline, "new", destination=destination)

    # v1 must be flagged as content_mismatch
    assert v1.status == "content_mismatch"
    # v2 must be picked
    assert picked is not None
    assert picked.video_id == "222"

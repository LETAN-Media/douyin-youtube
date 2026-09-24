import json
import pytest
from unittest.mock import patch, MagicMock
from app.ai_metadata import (
    evaluate_content_match,
    evaluate_content_level,
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


def _mock_ai_response(payload: dict):
    """Build a mock httpx.post returning an OpenAI-style JSON body."""
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_concert_caption_is_match_or_borderline():
    # Jason Derulo concert: music/crowd context, no explicit "dance" word.
    # Must NOT be a hard mismatch — MATCH or BORDERLINE only.
    caption = "好想冲下去加入他们 #jasonderulo杭州演唱会"
    niche = "Male dance performance, choreography, dance covers"
    prompt = open_prompt_override()

    with patch("app.ai_metadata.httpx.post") as mock_post, \
         patch.object(__import__("app.ai_metadata", fromlist=["settings"]).settings, "ai_api_key", "test-key"), \
         patch.object(__import__("app.ai_metadata", fromlist=["settings"]).settings, "ai_enabled", True):
        mock_post.return_value = _mock_ai_response({
            "verdict": "match",
            "reason": "Concert crowd context with music performance; audience wants to join dancing",
        })
        level, reason = evaluate_content_level(caption, niche=niche, prompt_override=prompt)

    assert level in ("match", "borderline"), reason
    # Boolean wrapper stays publishable for both levels
    matched, _ = evaluate_content_match(caption, niche=niche, prompt_override=prompt)
    assert matched is True


def open_prompt_override() -> str:
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "joybeat_dance.txt"
    return prompt_path.read_text(encoding="utf-8")


def test_concert_caption_heuristic_without_ai_key():
    # No API key -> heuristic path: concert keywords yield BORDERLINE, never mismatch.
    caption = "好想冲下去加入他们 #jasonderulo杭州演唱会"
    with patch.object(__import__("app.ai_metadata", fromlist=["settings"]).settings, "ai_api_key", ""), \
         patch.dict("os.environ", {"AI_API_KEY": ""}):
        level, reason = evaluate_content_level(
            caption,
            niche="Male dance performance",
            prompt_override="CONTENT RELEVANCE & SELECTION: dance and concert contexts accepted.",
        )
    assert level == "borderline", reason


def test_generate_never_blanks_on_mismatch():
    # Even a legacy CONTENT_MISMATCH-only AI reply must not blank fields:
    # title/description fall back to context draft, publish flow survives.
    dest = Destination(
        id="dest-joybeat-loose",
        name="JoyBeat Dance",
        metadata_profile="concert and lifestyle",
    )
    pipe = Pipeline(
        id="pipe-joybeat-loose",
        name="JoyBeat Dance",
        niche="general videos",
    )
    context = "今天去探店吃火锅 #美食 #探店"

    with patch("app.ai_metadata.httpx.post") as mock_post:
        # Pre-eval: channel not strict -> match, no AI call. Generation call
        # returns legacy mismatch shape with no usable fields.
        mock_post.return_value = _mock_ai_response({
            "status": "CONTENT_MISMATCH",
            "reason": "Not primarily dance",
        })
        gen = generate_metadata_structured(
            context_text=context, pipeline=pipe, destination=dest
        )

    assert gen is not None
    assert gen["title"], "title must never be blank"
    assert gen["description"], "description must never be blank"
    assert gen["final_description"], "final_description must never be blank"
    assert gen["match_level"] == "mismatch"
    assert gen["content_match"] is False


def test_generate_borderline_keeps_full_metadata():
    # BORDERLINE verdict still yields complete metadata + publishable flag.
    dest = Destination(
        id="dest-joybeat-border",
        name="JoyBeat Dance",
        metadata_profile="Male dance performance",
        prompt_override="CONTENT RELEVANCE & SELECTION advisory.",
    )
    pipe = Pipeline(id="pipe-joybeat-border", name="JoyBeat Dance", niche="dance")
    context = "好想冲下去加入他们 #jasonderulo杭州演唱会"

    ai_meta = {
        "title": "That concert energy hit different!",
        "description": "Watching Jason Derulo live and ready to jump in!",
        "hashtags": ["#streetdance", "#dancetrend", "#dance", "#concertvibes", "#live"],
        "match_level": "borderline",
        "reason": "Concert crowd context, plausibly dance-related",
    }
    with patch("app.ai_metadata.httpx.post") as mock_post:
        # Call order: pre-eval AI verdict, then metadata generation.
        mock_post.side_effect = [
            _mock_ai_response({"verdict": "borderline", "reason": "concert context"}),
            _mock_ai_response(ai_meta),
        ]
        with patch.object(__import__("app.ai_metadata", fromlist=["settings"]).settings, "ai_api_key", "test-key"), \
             patch.object(__import__("app.ai_metadata", fromlist=["settings"]).settings, "ai_enabled", True):
            gen = generate_metadata_structured(
                context_text=context, pipeline=pipe, destination=dest
            )

    assert gen is not None
    assert gen["title"] == ai_meta["title"]
    assert len(gen["hashtags"]) == 5
    assert gen["match_level"] == "borderline"
    assert gen["content_match"] is True


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

    # v1 must be rejected (held/rejected per policy; no inventory consumed)
    assert v1.status in ("rejected", "held", "content_mismatch")
    # v2 must be picked
    assert picked is not None
    assert picked.video_id == "222"


def test_joybeat_authentic_prompt_and_hashtags():
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "joybeat_dance.txt"
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "POSITIVE, JOYFUL & RADIANT ENERGY" in content
    assert "#streetdance" in content
    assert "#dancetrend" in content

    # Test hashtag validation with authentic JoyBeat tags
    dest = Destination(
        id="dest-joybeat-authentic",
        name="JoyBeat Dance",
        fixed_hashtags=["#streetdance", "#dancetrend", "#dance"],
        adaptive_hashtags=["#viraldance", "#dancecover", "#dancer"],
    )
    valid_desc = "Positive energy for today! ☀️\n\n#streetdance #dancetrend #dance #viraldance #dancer"
    assert validate_hashtags(valid_desc, destination=dest) is True


def _fluffy_channel():
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "fluffy_friends.txt"
    assert prompt_path.exists()
    prompt = prompt_path.read_text(encoding="utf-8")
    niche = "Cute pets and baby animals: cats, kittens, puppies, dogs, bunnies"
    return niche, prompt


def test_fluffy_cute_animals_match():
    from app.ai_metadata import settings as ai_settings
    niche, prompt = _fluffy_channel()
    with patch("app.ai_metadata.httpx.post") as mock_post, \
         patch.object(ai_settings, "ai_api_key", "test-key"), \
         patch.object(ai_settings, "ai_enabled", True):
        mock_post.return_value = _mock_ai_response({
            "verdict": "match",
            "reason": "Cute kitten content fits the pets niche",
        })
        level, _ = evaluate_content_level(
            "窝酱紫可爱吗 #米努特矮脚猫", niche=niche, prompt_override=prompt
        )
    assert level == "match"


def test_fluffy_finance_mismatch():
    from app.ai_metadata import settings as ai_settings
    niche, prompt = _fluffy_channel()
    with patch("app.ai_metadata.httpx.post") as mock_post, \
         patch.object(ai_settings, "ai_api_key", "test-key"), \
         patch.object(ai_settings, "ai_enabled", True):
        mock_post.return_value = _mock_ai_response({
            "verdict": "mismatch",
            "reason": "Stock market content unrelated to cute pets",
        })
        level, reason = evaluate_content_level(
            "今天股市大涨 #财经", niche=niche, prompt_override=prompt
        )
    assert level == "mismatch"
    assert "CONTENT_MISMATCH" in reason


def test_description_trailing_hashtags_stripped():
    # Model echoing hashtags inside description must not duplicate them in
    # final_description (worker requires exactly 5 tags).
    dest = Destination(id="d", name="X")
    pipe = Pipeline(id="p", name="X")
    payload = {
        "title": "So cute!",
        "description": "Look at those paws! #cutepets #cuteanimals #pets #kitten #adorable",
        "hashtags": ["#cutepets", "#cuteanimals", "#pets", "#kitten", "#adorable"],
    }
    with patch("app.ai_metadata.httpx.post") as mock_post:
        mock_post.return_value = _mock_ai_response(payload)
        gen = generate_metadata_structured(
            context_text="小猫 #kitten", pipeline=pipe, destination=dest
        )
    assert gen is not None
    assert "#" not in gen["description"]
    assert gen["final_description"].count("#") == 5
    assert validate_hashtags(gen["final_description"]) is True


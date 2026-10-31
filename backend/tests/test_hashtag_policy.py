import json
from types import SimpleNamespace as Profile
from unittest.mock import MagicMock, patch

import pytest

from app.hashtag_policy import (
    HashtagConfigurationError, clean_hashtag, compose_hashtags,
    repair_description, resolve_policy, validate_hashtags, validate_metadata,
)
from app.models import Pipeline


def profile(fixed=None, adaptive=None):
    return Profile(fixed_hashtags=fixed, adaptive_hashtags=adaptive)


@pytest.mark.parametrize('suggestions', [[], ['#a'], ['#a #b #c #d #e #f'], ['#tiktok']])
def test_suggestions_never_mandatory_or_injected(suggestions):
    p = profile(suggestions, ['#music #dance'])
    assert compose_hashtags(['#original'], p) == ['#original']
    assert validate_hashtags('#original', p) == (True, None)
    assert validate_hashtags('', p) == (True, None)


def test_destination_empty_overrides_and_none_inherits_without_mutation():
    p = profile(['#A #B #C'], ['#d'])
    assert resolve_policy(p, profile()) == (['#a', '#b', '#c'], ['#d'])
    assert resolve_policy(p, profile([], [])) == ([], [])
    assert resolve_policy(profile(['#x']))[0] == ['#x']
    assert p.fixed_hashtags == ['#A #B #C']


def test_duplicates_banned_invalid_and_no_filler():
    result = repair_description('Original prose.\n\n#BRAND #brand #TikTok #bad-tag #music')
    assert result == 'Original prose.\n\n#brand #music'
    assert validate_metadata('Natural video title', result) == (True, None)
    assert compose_hashtags(['#same', '#SAME', '#tiktok']) == ['#same']


@pytest.mark.parametrize('tag', ['#httpx', '#douyinclip', '#TikTok', '#joybeat', '#daniel', '#bad-tag', '#x!'])
def test_banned_and_invalid_tags(tag):
    assert not clean_hashtag(tag)
    assert not validate_hashtags(tag)[0]


def test_at_most_five_without_minimum():
    assert compose_hashtags(['#a #b #c #d #e #f']) == ['#a', '#b', '#c', '#d', '#e']
    assert not validate_hashtags('#a #b #c #d #e #f')[0]
    assert not validate_hashtags('#a #A')[0]


@pytest.mark.parametrize('title,desc,valid', [
    ('', 'Description', False), ('   ', '', False),
    ('x' * 100, 'x' * 5000, True), ('x' * 101, '', False),
    ('Title', 'x' * 5001, False), ('Title', 'https://douyin.com/video/1', False),
    ('Title', '复制打开抖音', False), ('Title', 'A meaningful description.', True),
])
def test_metadata_limits(title, desc, valid):
    assert validate_metadata(title, desc)[0] is valid


def test_dna_locks_remain_separate_and_no_silent_truncation():
    assert compose_hashtags(['#topic'], profile(['#optional']), locked=['#brand']) == ['#brand', '#topic']
    assert not validate_metadata('Title', '#topic', locked=['#brand'])[0]
    for locked in [['#a #b #c #d #e #f'], ['#tiktok']]:
        with pytest.raises(HashtagConfigurationError):
            compose_hashtags([], locked=locked)


def test_generator_uses_pipeline_language_prompt_and_only_relevant_ai_tags():
    from app.ai_metadata import generate_metadata_structured, settings
    p = Pipeline(name='Test', niche='Dance', language='vi', prompt_profile='Phong cách tự nhiên.', fixed_hashtags=['#unrelated #unused'], adaptive_hashtags=['#dance'])
    payload = {'title': 'Vũ điệu đầy năng lượng trên sân khấu', 'description': 'Những bước nhảy ăn ý theo nhịp nhạc. #dance', 'hashtags': ['#Dance', '#choreography', '#tiktok', '#bad-tag']}
    response = MagicMock()
    response.text = json.dumps({'choices': [{'message': {'content': json.dumps(payload)}}]})
    with patch.object(settings, 'ai_api_key', 'test'), patch.object(settings, 'ai_enabled', True), patch('app.ai_metadata.evaluate_content_level', return_value=('match', 'dance')), patch('app.ai_metadata.httpx.post', return_value=response) as post:
        result = generate_metadata_structured('舞蹈 dance', pipeline=p)
    assert result['title'] == payload['title']
    assert result['description'] == 'Những bước nhảy ăn ý theo nhịp nhạc.'
    assert result['hashtags'] == ['#dance', '#choreography']
    assert validate_metadata(result['title'], result['final_description'])[0]
    messages = post.call_args.kwargs['json']['messages']
    assert 'Phong cách tự nhiên.' in messages[0]['content']
    assert 'Language: vi' in messages[1]['content']
    assert 'optional' in messages[0]['content']


def test_retry_rejects_existing_publication_or_job_video_id():
    from fastapi import HTTPException
    from app.main import _guard_publication_retry
    db = MagicMock()
    pub = Profile(id='p', external_post_id=None, external_url=None)
    db.scalar.return_value = None
    _guard_publication_retry(db, pub)
    pub.external_post_id = 'existing-youtube-id'
    with pytest.raises(HTTPException) as exc:
        _guard_publication_retry(db, pub)
    assert exc.value.status_code == 409
    pub.external_post_id = None
    db.scalar.return_value = Profile(youtube_video_id='existing-job-video-id')
    with pytest.raises(HTTPException):
        _guard_publication_retry(db, pub)


def test_configured_youtube_cta_is_allowed_but_source_share_text_is_not():
    from app.worker import validate_final_description
    text = 'Watch this choreography. Subscribe: https://www.youtube.com/channel/example\n\n#dance'
    assert validate_final_description(text)
    assert validate_metadata('A natural title', text)[0]
    assert not validate_final_description('https://v.douyin.com/example')


@pytest.mark.parametrize('raw_title,raw_description,tags,expected_count,returns_metadata', [
    ('x' * 140, 'A real description.', ['#topic'], 1, True),
    ('Title', 'A real description.', [], 0, True),
    ('Title', 'A real description.', ['#a #b #c #d #e #f'], 5, True),
    ('Title', 'x' * 5001, ['#topic'], 0, False),
    ('', '', [], 0, False),
])
def test_generator_bad_ai_output_limits(raw_title, raw_description, tags, expected_count, returns_metadata):
    from app.ai_metadata import generate_metadata_structured, settings
    response = MagicMock()
    response.text = json.dumps({'choices': [{'message': {'content': json.dumps({'title': raw_title, 'description': raw_description, 'hashtags': tags})}}]})
    with patch.object(settings, 'ai_api_key', 'test'), patch.object(settings, 'ai_enabled', True), patch('app.ai_metadata.evaluate_content_level', return_value=('match', 'topic')), patch('app.ai_metadata.httpx.post', return_value=response) as post:
        result = generate_metadata_structured('')
    assert bool(result) is returns_metadata
    assert post.call_count == 1
    if result:
        assert len(result['title']) <= 100
        assert len(result['hashtags']) == expected_count
        assert validate_metadata(result['title'], result['final_description'])[0]

"""Shared metadata contract. Profile hashtags are suggestions; DNA locks are separate."""
import re

MAX_HASHTAGS = 5


class HashtagConfigurationError(ValueError):
    """A mandatory DNA rule conflicts with metadata safety limits."""


def clean_hashtag(value: str) -> str:
    tag = re.sub(r"\s+", "", str(value).strip().lower()).lstrip('#')
    if not tag or not re.fullmatch(r"\w+", tag) or len(tag) > 59:
        return ""
    if 'http' in tag or 'douyin' in tag or tag in {'tiktok', 'joybeat', 'danielxu', 'danniu', 'daniel'}:
        return ""
    return '#' + tag


def tag_tokens(values):
    if isinstance(values, str):
        values = [values]
    return [token for value in values or [] for token in re.split(r"[\s,]+", str(value).strip()) if token]


def unique_tags(values):
    return list(dict.fromkeys(t for v in tag_tokens(values) if (t := clean_hashtag(v))))


def resolve_policy(pipeline=None, destination=None):
    """None inherits; an explicit empty list clears inherited suggestions."""
    def inherited(name):
        value = getattr(destination, name, None)
        return (getattr(pipeline, name, None) if value is None else value) or []
    return unique_tags(inherited('fixed_hashtags')), unique_tags(inherited('adaptive_hashtags'))


def compose_hashtags(candidates, pipeline=None, destination=None, locked=None):
    # Relevance selection belongs to the AI. Never inject unselected suggestions.
    raw_locked = tag_tokens(locked)
    invalid = [t for t in raw_locked if not clean_hashtag(t)]
    core = unique_tags(raw_locked)
    if invalid or len(core) > MAX_HASHTAGS:
        raise HashtagConfigurationError(
            f'Locked DNA hashtags conflict with safety/maximum {MAX_HASHTAGS}: {invalid or core}'
        )
    return (core + [t for t in unique_tags(candidates) if t not in core])[:MAX_HASHTAGS]


def validate_hashtags(text, pipeline=None, destination=None, locked=None):
    raw = re.findall(r'#[^\s#]+', text)
    tags = [clean_hashtag(t) for t in raw]
    errors = []
    invalid = [t for t, clean in zip(raw, tags) if not clean]
    if invalid:
        errors.append(f'Invalid or banned hashtags: {invalid}')
    if len(raw) > MAX_HASHTAGS:
        errors.append(f'Expected at most {MAX_HASHTAGS} hashtags, found {len(raw)}')
    if len(set(tags)) != len(tags):
        errors.append('Duplicate hashtags found (case insensitive)')
    try:
        core = compose_hashtags([], locked=locked)
        missing = [t for t in core if t not in tags]
        if missing:
            errors.append(f'Missing locked DNA hashtags: {missing}')
    except HashtagConfigurationError as exc:
        errors.append(str(exc))
    return (False, '; '.join(errors)) if errors else (True, None)


def repair_description(text, pipeline=None, destination=None, locked=None):
    raw = re.findall(r'#[^\s#]+', text)
    tags = compose_hashtags(raw, locked=locked)
    if raw == tags:
        return text
    prose = re.sub(r'#[^\s#]+', '', text).rstrip()
    return prose + ('\n\n' + ' '.join(tags) if tags else '')


def validate_metadata(title, description, locked=None):
    if not title or not title.strip():
        return False, 'Title must not be empty'
    if len(title) > 100:
        return False, 'Title exceeds 100 characters'
    if len(description) > 5000:
        return False, 'Description exceeds 5000 characters'
    if re.search(r'douyin\.com|复制打开抖音|复制此链接|打开抖音', description, re.I):
        return False, 'Description contains source/share URLs or text'
    return validate_hashtags(description, locked=locked)

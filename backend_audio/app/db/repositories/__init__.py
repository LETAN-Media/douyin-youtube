"""Shared repo helpers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


import unicodedata


def slugify(name: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", name or "") if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    slug = re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")
    return slug or f"pipeline_{uuid.uuid4().hex[:6]}"

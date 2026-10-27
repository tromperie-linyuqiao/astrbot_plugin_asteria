"""Exact text-helper dependency closure for the native summary algorithm.

No turn classifier, old plugin import, network, store or lifecycle is included.
"""
from __future__ import annotations

import json
import re
from typing import Any

def clean_text(value: Any, limit: int = 2000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


TERM_STOPWORDS = {
    "给我",
    "你的",
    "一张",
    "一下",
    "这个",
    "那个",
    "什么",
    "怎么",
    "为什么",
    "可以",
    "是不是",
    "有没有",
    "知道",
    "当前",
    "用户",
}


def _compact_message(text: str) -> str:
    value = clean_text(text, 1200)
    value = re.sub(r"\[At:\d+\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"@\S+", "", value)
    value = re.sub(r"[\s,，。.!！~～…、:：;；\"'“”‘’()（）\[\]【】<>《》]+", "", value)
    return value.lower()


def message_terms(text: str, *, limit: int = 40) -> list[str]:
    compact = _compact_message(text)
    if not compact:
        return []
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9_]{2,}", compact))
    chinese = re.findall(r"[\u4e00-\u9fff]+", compact)
    for block in chinese:
        if len(block) <= 1:
            continue
        if len(block) <= 4:
            terms.append(block)
        for size in (2, 3, 4):
            if len(block) < size:
                continue
            terms.extend(block[index : index + size] for index in range(0, len(block) - size + 1))
    filtered = [
        term
        for term in terms
        if len(term) >= 2 and term not in TERM_STOPWORDS and not _is_stopword_like(term)
    ]
    return list(dict.fromkeys(filtered))[:limit]


def _is_stopword_like(term: str) -> bool:
    if term in TERM_STOPWORDS:
        return True
    if re.fullmatch(r"[的是了嘛吗呢吧呀哦啊]+", term):
        return True
    return False

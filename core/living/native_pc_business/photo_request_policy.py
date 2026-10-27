"""Pure image request shaping; no provider, credentials, state, or I/O access.

The NAI override is an adapter contract whose support by a remote
OpenAI-compatible service must be verified from that service's returned image
metadata; a model name alone cannot prove that a third-party service supports it.
"""
from __future__ import annotations

import re
from typing import Any

from .photo_clothing import split_photo_prompt


_NAI_MODEL = re.compile(r"^(?:novelai/)?nai-diffusion(?:-|$)", re.I)
_OPENAI_PLATFORMS = frozenset({"", "auto", "openai", "novelai", "nai"})
_ENGLISH_LABEL = re.compile(r"\b(positive|negative)(?:[\s_-]+prompt)?\s*[:：]", re.I)
_SINGLE_SCENE = "A single image depicting one continuous scene in a single frame."
_VISUAL_EXCLUSIONS = re.compile(
    r"\b(?:collage|grid|panels?|diptych|triptych|contact sheet|character sheet|"
    r"split screen|side[- ]by[- ]side|duplicat(?:e|ed) (?:character|subject)|"
    r"twins|multiple (?:people|outfits)|outfit (?:alternatives|comparison)|"
    r"comparison (?:layout|panels)|before and after|mirror selfie|mirror|"
    r"full[- ](?:length|body) mirror|phone covering face|"
    r"nude|naked|topless|bottomless|unclothed|missing clothes|outfit removal)\b|"
    r"拼图|宫格|多格|分屏|裸体|裸身|全裸|不穿衣服",
    re.I,
)
_NEGATION_START = re.compile(
    r"^(?:but\s+)?(?:do\s+not(?:\s+(?:create|include|show|add))?|"
    r"no|not|avoid|exclude|without)\s+(?:(?:any|a|an|the)\s+)?|"
    r"^(?:不要|避免|不许|禁止)(?:出现|生成|添加)?\s*",
    re.I,
)
_DEFAULT_NEGATIVE = (
    "collage", "grid layout", "split screen", "multiple panels", "contact sheet",
    "character sheet", "duplicate character", "nude", "naked", "topless",
    "bottomless", "unclothed", "missing clothes", "unrequested outfit removal",
)


def is_nai_image_model(*, model: str, platform: str = "openai") -> bool:
    """Limit the private NAI payload extension to its known diffusion namespace."""
    return (str(platform or "").strip().lower() in _OPENAI_PLATFORMS
            and bool(_NAI_MODEL.match(str(model or "").strip())))


def _normalise_labels(prompt: str) -> str:
    value = _ENGLISH_LABEL.sub(lambda match: match.group(1).title() + " prompt:", prompt)
    return re.sub(r"(正向|正面|负向|负面)(?:提示词|提示)?\s*[:：]",
                  lambda match: "Positive prompt:" if match.group(1) in {"正向", "正面"} else "Negative prompt:", value)


def _move_visual_exclusions(positive: str) -> tuple[str, list[str]]:
    """Move explicit visual exclusions, including comma-list continuations.

    This only handles exclusions already written as such. Ordinary scene,
    character, garment, and style descriptions are retained.
    """
    kept: list[str] = []
    moved: list[str] = []
    continuation = False
    # A decimal point inside existing weighting syntax is not a sentence end:
    # preserve both NAI ``1.2::garment::`` and ``(garment:1.3)`` verbatim.
    for piece in re.split(r"((?:[,;；。!?]|(?<!\d)\.|\.(?!\d))+)", positive):
        text = piece.strip()
        if not text:
            continue
        if re.fullmatch(r"[,;；。.!?]+", text):
            if kept:
                kept[-1] = kept[-1].rstrip(" ,;；。.!?") + text
            if any(mark in text for mark in ";；。.!?"):
                continuation = False
            continue
        marker = _NEGATION_START.match(text)
        visual_matches = list(_VISUAL_EXCLUSIONS.finditer(text))
        visual = bool(visual_matches)
        # Plain "mirror" is only an explicit exclusion. A requested mirror
        # scene must not inherit a preceding comma-list's negative scope.
        inherited_visual = any(match.group().casefold() != "mirror" for match in visual_matches)
        if (marker and visual) or (continuation and inherited_visual):
            clause = text[marker.end():] if marker else re.sub(r"^(?:and|or)\s+", "", text, flags=re.I)
            clause = re.sub(r"\s+unless (?:explicitly )?requested\b.*$", "", clause, flags=re.I)
            if clause.strip():
                moved.append(clause.strip())
            continuation = True
        else:
            kept.append(text)
            continuation = False
    return " ".join(kept).strip(" ,;；。.!?"), moved


def _negative_terms(parts: list[str]) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for value in re.split(r"[,;；]+", str(part or "")):
            text = re.sub(r"\s+", " ", value).strip(" ,;；。.")
            key = text.casefold()
            if text and key not in seen:
                terms.append(text)
                seen.add(key)
    return ", ".join(terms)


def build_openai_image_payload(
    *, model: str, platform: str, prompt: str, size: str,
    workflow_kind: str = "text2img",
) -> dict[str, Any]:
    """Build one-image requests without changing unrelated provider protocols.

    ``workflow_kind`` is accepted for a stable caller interface. The single-scene
    rule applies equally to selfies, character drawings, and environment scenes;
    it does not add a character to a landscape or select a new outfit.
    """
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if not is_nai_image_model(model=model, platform=platform):
        return payload
    positive, negative = split_photo_prompt(_normalise_labels(str(prompt or "")))
    positive, moved = _move_visual_exclusions(positive)
    # Prefix after all upstream merges so long scene descriptions cannot push
    # this instruction outside the request's leading text. No later truncation.
    if positive.startswith(_SINGLE_SCENE):
        shaped = positive
    else:
        shaped = _SINGLE_SCENE + (" " + positive if positive else "")
    payload["prompt"] = shaped
    payload["negative_prompt"] = _negative_terms([negative, *moved, *_DEFAULT_NEGATIVE])
    return payload

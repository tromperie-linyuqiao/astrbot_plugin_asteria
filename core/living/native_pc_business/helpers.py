# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import time
import unicodedata
import zoneinfo
import math
from datetime import date, datetime, timedelta
from typing import Any

try:
    from lunarcalendar import festival as _special_lunar_festival
except Exception:
    _special_lunar_festival = None

_today_key_timezone = ""

_GROUP_MESSAGE_URL_PATTERN = re.compile(
    r"(?i)(?<![\w@])(?:https?://|www\.)[^\s<>\"“”‘’]+"
)
_GROUP_SHARE_MARKER_PATTERN = re.compile(
    r"(?i)(?:"
    r"[\[【](?:分享|链接|网页|网页分享|卡片|小程序|QQ小程序|转发消息|合并转发|JSON消息|XML消息)[\]】]"
    r"|\[CQ:(?:json|xml|share|miniapp)\b[^\]]*\]"
    r")"
)
_GROUP_SHARE_BOILERPLATE_PATTERN = re.compile(
    r"(?i)(?:"
    r"当前\s*QQ\s*版本不支持(?:此|该)?应用[，,、\s]*请升级"
    r"|当前\s*QQ\s*版本不支持查看(?:此|该)?内容[，,、\s]*请升级"
    r"|(?:你的|您(?:的)?|当前)?\s*QQ\s*版本过低[，,、\s]*"
    r"(?:暂不支持查看(?:此|该)?内容|请(?:升级|更新)(?:后)?查看)"
    r"|请使用最新版本(?:手机)?\s*QQ\s*查看"
    r")"
)


def _now_ts() -> float:
    return time.time()


def _normalize_timezone_name(timezone_name: Any, default: str = "Asia/Shanghai") -> str:
    candidate = str(timezone_name or "").strip() or default
    try:
        zoneinfo.ZoneInfo(candidate)
        return candidate
    except Exception:
        return default


def _set_today_key_timezone(timezone_name: Any) -> None:
    global _today_key_timezone
    _today_key_timezone = _normalize_timezone_name(timezone_name)


def _today_key() -> str:
    if _today_key_timezone:
        try:
            return datetime.now(zoneinfo.ZoneInfo(_today_key_timezone)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def _date_key(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _safe_int(value: Any, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _safe_float(
    value: Any,
    default: float,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _single_line(text: Any, limit: int = 80) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized[:limit]


def _normalize_photo_subject_owner(value: Any) -> str:
    normalized = _single_line(value, 40).strip().lower().replace("-", "_")
    if normalized in {"bot", "self", "persona", "character", "当前人格", "机器人", "角色本人"}:
        return "bot"
    if normalized in {"third_party", "thirdparty", "other_person", "第三方", "第三方人物", "其他人物"}:
        return "third_party"
    if normalized in {"scene", "object", "animal", "environment", "画面", "物体", "动物", "环境"}:
        return "scene"
    if normalized in {"unknown", "unclear", "ambiguous", "未知", "不明", "无法判断"}:
        return "unknown"
    return ""


def _photo_subject_owner_prompt_label(value: Any) -> str:
    owner = _normalize_photo_subject_owner(value) or "unknown"
    return {
        "bot": "Bot/当前人格（图片描述中的“我/她/角色本人”）",
        "third_party": "画面中的第三方人物（不是 Bot，也不是用户）",
        "scene": "画面中的物体、动物或环境主体（不是用户）",
        "unknown": "画面中的实际主体（归属不明，但不能据此归到用户）",
    }[owner]


def _group_link_message_context(text: Any, limit: int = 260) -> tuple[str, bool]:
    """Return non-link user text and whether the message contains a link/share payload."""
    raw = str(text or "")[:4000].replace("\u200b", "").replace("\ufeff", "")
    has_link_payload = bool(
        _GROUP_MESSAGE_URL_PATTERN.search(raw)
        or _GROUP_SHARE_MARKER_PATTERN.search(raw)
        or _GROUP_SHARE_BOILERPLATE_PATTERN.search(raw)
    )
    if not has_link_payload:
        return _single_line(raw, limit), False
    remainder = _GROUP_MESSAGE_URL_PATTERN.sub(" ", raw)
    remainder = _GROUP_SHARE_MARKER_PATTERN.sub(" ", remainder)
    remainder = _GROUP_SHARE_BOILERPLATE_PATTERN.sub(" ", remainder)
    remainder = re.sub(r"(?i)(?:网页)?(?:链接|网址|link)\s*[:：]", " ", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip(" \t\r\n,，。;；|｜-—")
    return _single_line(remainder, limit), True


_SECRET_FIELD_PATTERN = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|auth[_ -]?token|secret|password|passwd|cookie|密钥|令牌|口令)",
    flags=re.IGNORECASE,
)


def _runtime_secret_values(owner: Any) -> list[str]:
    """Collect configured credentials without exposing them to logs or prompts."""
    values: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, (str, bytes)):
            text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
            text = text.strip()
            if len(text) >= 6:
                values.add(text)

    for attr in (
        "external_image_api_key",
        "backup_external_image_api_key",
        "balance_api_key",
        "weather_api_key",
        "web_exploration_api_key",
    ):
        add(getattr(owner, attr, ""))
    endpoints = getattr(owner, "external_image_api_endpoints", None)
    if isinstance(endpoints, list):
        for endpoint in endpoints[:24]:
            if not isinstance(endpoint, dict):
                continue
            for key, value in endpoint.items():
                if _SECRET_FIELD_PATTERN.search(str(key or "")):
                    add(value)

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        try:
            items = value.items() if hasattr(value, "items") else None
        except Exception:
            items = None
        if items is not None:
            try:
                for key, child in list(items)[:500]:
                    if _SECRET_FIELD_PATTERN.search(str(key or "")):
                        add(child)
                    elif isinstance(child, (dict, list, tuple)) or hasattr(child, "items"):
                        walk(child, depth + 1)
            except Exception:
                return
        elif isinstance(value, (list, tuple)):
            for child in value[:100]:
                if isinstance(child, (dict, list, tuple)) or hasattr(child, "items"):
                    walk(child, depth + 1)

    walk(getattr(owner, "config", None))
    return sorted(values, key=len, reverse=True)


def _redact_outbound_secrets(text: Any, owner: Any = None) -> str:
    """Redact credentials from chat-bound text while preserving the useful reply."""
    cleaned = str(text or "")
    if not cleaned:
        return ""
    for secret in _runtime_secret_values(owner) if owner is not None else []:
        cleaned = cleaned.replace(secret, "[密钥已隐藏]")
    patterns = (
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [密钥已隐藏]"),
        (r"(?i)\b(?:sk|pk|rk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{10,}", "[密钥已隐藏]"),
        (r"\bAIza[A-Za-z0-9_-]{20,}\b", "[密钥已隐藏]"),
        (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b", "[密钥已隐藏]"),
        (r"(?i)([?&](?:api[_-]?key|access_token|refresh_token|token|secret|key)=)[^&#\s]+", r"\1[密钥已隐藏]"),
        (
            r"(?i)((?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|auth[_ -]?token|secret|password|passwd|密钥|令牌|口令)\s*(?::|：|=)\s*[\"']?)[^\s,，;；\"']{6,}",
            r"\1[密钥已隐藏]",
        ),
    )
    for pattern, replacement in patterns:
        cleaned = re.sub(pattern, replacement, cleaned)
    return cleaned


_OPTIONAL_MODEL_DEPENDENCIES = {
    "torch",
    "torchvision",
    "torchaudio",
    "sentence_transformers",
    "transformers",
}


def _missing_optional_model_dependency(exc: BaseException) -> str:
    if isinstance(exc, ModuleNotFoundError):
        name = str(getattr(exc, "name", "") or "").strip()
        if name in _OPTIONAL_MODEL_DEPENDENCIES:
            return name
    text = str(exc or "")
    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", text)
    if not match:
        return ""
    name = match.group(1).strip()
    return name if name in _OPTIONAL_MODEL_DEPENDENCIES else ""


_GARBLED_TEXT_MARKERS = ("Ã", "â", "鈥", "銆", "鏉", "锟", "Ð", "Ê", "¤", "\ufffd")
_BINARY_TEXT_PREFIXES = ("JFIF", "EXIF", "GIF87A", "GIF89A", "%PDF-", "PK\x03\x04")


def _text_looks_garbled(text: Any) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return False
    head = compact[:32].upper()
    if any(head.startswith(prefix) for prefix in _BINARY_TEXT_PREFIXES):
        return True
    replacement_count = compact.count("\ufffd")
    if replacement_count >= 2:
        return True
    mojibake_count = sum(compact.count(marker) for marker in _GARBLED_TEXT_MARKERS if marker != "\ufffd")
    if mojibake_count >= 3 and len(compact) >= 12:
        return True
    control_count = 0
    for ch in compact[:400]:
        if ch in "\n\r\t":
            continue
        if unicodedata.category(ch).startswith("C"):
            control_count += 1
    return control_count >= 2


def _strip_internal_message_blocks(text: Any) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"\[\[TTSBLOCK:[^\]]*\]\]", "", normalized)
    normalized = re.sub(r"\[\[PCTTS:[^\]]*\]\]", "", normalized)
    normalized = re.sub(r"<timer\b[^>]*>.*?</timer>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<tts\b[^>]*>.*?</tts>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<think\b[^>]*>.*?</think>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = _strip_nonstandard_chat_control_tags(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


_CHAT_SELF_CLOSING_TAG_ALLOWLIST = (
    r"br|image|img|video|audio|record|file|at|face|emoji|reply|tts|pc[_-]?tts|timer"
)

_NONSTANDARD_SELF_CLOSING_TAG_PATTERN = re.compile(
    rf"<\s*(?!(?:{_CHAT_SELF_CLOSING_TAG_ALLOWLIST})\b)"
    r"[A-Za-z][A-Za-z0-9_-]{0,31}(?:\s+[^<>\r\n]{0,160})?/\s*>",
    re.IGNORECASE,
)
_ESCAPED_NONSTANDARD_SELF_CLOSING_TAG_PATTERN = re.compile(
    rf"&lt;\s*(?!(?:{_CHAT_SELF_CLOSING_TAG_ALLOWLIST})\b)"
    r"[A-Za-z][A-Za-z0-9_-]{0,31}(?:\s+[^&\r\n]{0,160})?/\s*&gt;",
    re.IGNORECASE,
)
_MARKDOWN_CODE_SPAN_PATTERN = re.compile(
    r"(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\r\n]+`)",
    re.MULTILINE,
)


def _strip_nonstandard_chat_control_tags(text: Any) -> str:
    """Remove leaked pseudo-control tags such as <bubble/> without touching media blocks."""
    normalized = str(text or "")
    if not normalized:
        return ""
    normalized = _NONSTANDARD_SELF_CLOSING_TAG_PATTERN.sub("", normalized)
    normalized = _ESCAPED_NONSTANDARD_SELF_CLOSING_TAG_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+([，,。！？!?；;：:、~～…])", r"\1", normalized)
    normalized = re.sub(r"([（(【\[])\s+", r"\1", normalized)
    normalized = re.sub(r"\s+([）)】\]])", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized


def _strip_persisted_chat_control_tags(text: Any) -> str:
    """Clean leaked controls while preserving literal tags shown as Markdown code."""
    normalized = str(text or "")
    if not normalized:
        return ""
    parts = _MARKDOWN_CODE_SPAN_PATTERN.split(normalized)
    for index in range(0, len(parts), 2):
        parts[index] = _strip_nonstandard_chat_control_tags(parts[index])
    return "".join(parts)


def _strip_outbound_control_blocks(
    text: Any,
    *,
    preserve_private_tts_tokens: bool = False,
    allowed_private_tts_tokens: set[str] | None = None,
) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"\[\[TTSBLOCK:[^\]]*\]\]", "", normalized)
    if preserve_private_tts_tokens and allowed_private_tts_tokens:
        allowed = {str(token) for token in allowed_private_tts_tokens if str(token)}

        def _private_tts_repl(match: re.Match[str]) -> str:
            token = str(match.group(1) or "")
            return match.group(0) if token in allowed else ""

        normalized = re.sub(r"\[\[PCTTS:([^\]]*)\]\]", _private_tts_repl, normalized)
    elif not preserve_private_tts_tokens:
        normalized = re.sub(r"\[\[PCTTS:[^\]]*\]\]", "", normalized)
    normalized = re.sub(r"<timer\b[^>]*>.*?</timer>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<think\b[^>]*>.*?</think>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = _strip_nonstandard_chat_control_tags(normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def _normalize_outbound_punctuation_flow(text: Any) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""
    soft = "呢呀啊嘛吧哦喔诶欸啦哇哟"
    short_token = r"(?:[A-Za-z0-9_\-/\\]{1,60}|[\u4e00-\u9fff]{1,10}|[\u4e00-\u9fffA-Za-z0-9_\-/\\]{1,24})"
    normalized = re.sub(
        rf"([A-Za-z0-9_\-/\\]{{1,60}})[。！？!?]\s+([{soft}])(?=[，,。！？!?~～\s]|$)",
        r"\1\2",
        normalized,
    )
    normalized = re.sub(
        rf"({short_token})[。！？!?]\s+([{soft}])(?=[，,。！？!?~～\s]|$)",
        r"\1\2",
        normalized,
    )
    normalized = re.sub(
        rf"(/[A-Za-z0-9_\-\u4e00-\u9fff]{{1,24}})[，,]\s*([{soft}])(?=[。！？!?~～\s]|$)",
        r"\1 \2",
        normalized,
    )
    command_like = r"(?:[A-Za-z0-9_\-]{1,24}|[\u4e00-\u9fff]{1,8}(?:/[\u4e00-\u9fffA-Za-z0-9_\-]{1,12})+)"
    normalized = re.sub(
        rf"({command_like})[，,]\s*([{soft}])(?=[。！？!?~～\s]|$)",
        r"\1\2",
        normalized,
    )
    normalized = re.sub(
        rf"([A-Za-z0-9_\-/\\]{{1,60}})[，,]\s*([{soft}])(?=[。！？!?~～\s]|$)",
        r"\1\2",
        normalized,
    )
    normalized = re.sub(
        rf"([\u4e00-\u9fff]{{1,10}})[，,]\s*([{soft}])(?=[。！？!?~～\s]|$)",
        r"\1\2",
        normalized,
    )
    return normalized


def _semantic_text_compact(text: Any) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"^(?:读后感|画面记录|札记\s*\d*|笔记\s*\d*)[:：]\s*", "", normalized.strip())
    normalized = re.sub(r"[\s\r\n\t\"'“”‘’《》【】\[\]（）(){}<>.,，。！？!?；;：:、~～…—_\-]+", "", normalized)
    return normalized.lower()


def _text_similarity(left: Any, right: Any) -> float:
    a = _semantic_text_compact(left)
    b = _semantic_text_compact(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 12 and shorter in longer:
        return len(shorter) / max(1, len(longer))

    def grams(value: str) -> set[str]:
        if len(value) <= 2:
            return {value}
        return {value[index : index + 2] for index in range(len(value) - 1)}

    left_grams = grams(a)
    right_grams = grams(b)
    overlap = len(left_grams & right_grams)
    union = len(left_grams | right_grams)
    if union <= 0:
        return 0.0
    return overlap / union


_LEGACY_TAG_PATTERN = re.compile(r"&&([A-Za-z_][A-Za-z0-9_]*)&&")
_LEGACY_TAG_CANONICAL_ALIASES = {
    "morning": "morning_greeting",
    "noon": "noon_greeting",
    "evening": "evening_greeting",
    "daily_greeting": "daily_greeting",
    "pending_followup": "pending_followup",
    "followup": "pending_followup",
    "random": "random",
    "state": "state_share",
    "event": "event",
    "group": "group_share",
    "diary": "diary_share",
    "check_in": "check_in",
    "quiet_care": "quiet_care",
}
_LEGACY_TAG_LABEL_ALIASES = {
    "morning_greeting": "早安",
    "noon_greeting": "午安",
    "evening_greeting": "晚安",
    "daily_greeting": "日常招呼",
    "pending_followup": "补一句",
    "random": "轻微想念",
    "state_share": "身体状态",
    "event": "具体事件",
    "group_share": "群里那点事",
    "diary_share": "日记碎片",
    "check_in": "顺手问候",
    "quiet_care": "轻轻关心",
}


def normalize_legacy_tag_text(value: Any, *, label: bool = False) -> str:
    text = str(value or "")
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        token = str(match.group(1) or "").strip().lower()
        canonical = _LEGACY_TAG_CANONICAL_ALIASES.get(token, token)
        if label:
            return _LEGACY_TAG_LABEL_ALIASES.get(canonical, canonical.replace("_", " ") if canonical else "")
        return canonical

    normalized = _LEGACY_TAG_PATTERN.sub(_replace, text)
    return normalized.strip()


_MISSING = object()


def _flat_get(config: Any, key: str, default: Any = None) -> Any:
    """Read both flat config keys and keys nested under schema object/items groups."""
    if isinstance(config, dict):
        # Prefer schema-group values over top-level legacy compatibility keys.
        # AstrBot may add invisible legacy flat defaults before plugin init; if
        # those are read first they would shadow the user's real grouped config.
        for value in config.values():
            if isinstance(value, dict):
                found = _flat_get(value, key, _MISSING)
                if found is not _MISSING:
                    return found
        if key in config:
            return config[key]
    for attr in ("data", "config"):
        target = getattr(config, attr, None)
        if isinstance(target, dict):
            found = _flat_get(target, key, _MISSING)
            if found is not _MISSING:
                return found
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(key, _MISSING)
        except Exception:
            value = _MISSING
        if value is not _MISSING:
            return value
    return default


def _set_into_config(config: Any, key: str, value: Any, *, allow_flat_fallback: bool = True) -> bool:
    """Write a config value back to its existing flat or nested location."""

    def convert(existing: Any, new_value: Any) -> Any:
        if isinstance(existing, bool) and isinstance(new_value, str):
            text = new_value.strip().lower()
            if text in {"true", "1", "yes", "y", "on", "enable", "enabled", "启用", "开启", "开", "是"}:
                return True
            if text in {"false", "0", "no", "n", "off", "disable", "disabled", "停用", "关闭", "关", "否", ""}:
                return False
        if isinstance(existing, int) and not isinstance(existing, bool) and isinstance(new_value, str):
            try:
                return int(new_value)
            except (TypeError, ValueError):
                return new_value
        if isinstance(existing, float) and isinstance(new_value, str):
            try:
                return float(new_value)
            except (TypeError, ValueError):
                return new_value
        return new_value

    def find_and_set(target: dict[str, Any]) -> bool:
        # Match _flat_get(): schema-grouped values are searched before legacy
        # flat compatibility keys.  When a key exists in more than one place,
        # keep every location in sync so later readers cannot see a stale copy.
        changed = False
        for child in target.values():
            if isinstance(child, dict):
                changed = find_and_set(child) or changed
        if key in target:
            target[key] = convert(target.get(key), value)
            changed = True
        return changed

    if isinstance(config, dict) and find_and_set(config):
        return True
    for attr in ("data", "config"):
        target = getattr(config, attr, None)
        if isinstance(target, dict) and find_and_set(target):
            return True
    if not allow_flat_fallback:
        return False
    try:
        config[key] = value
        return True
    except Exception:
        pass
    setter = getattr(config, "set", None)
    if callable(setter):
        try:
            setter(key, value)
            return True
        except Exception:
            pass
    return False


# These settings describe dates only. They never create scopes, tasks or sends.
_SPECIAL_TIMEZONE = "Asia/Shanghai"
_SPECIAL_HOLIDAYS = (
    ("new_year", "元旦", "solar", (1, 1)),
    ("laba", "腊八节", "lunar", "LaBa"),
    ("little_new_year", "北方小年", "lunar", "XiaoNian"),
    ("chinese_new_year_eve", "除夕", "lunar", "NewYearEve"),
    ("spring_festival", "春节", "lunar", "ChineseNewYear"),
    ("lantern", "元宵节", "lunar", "Lantern"),
    ("dragon_head", "龙抬头", "lunar", "DragonHead"),
    ("valentines_day", "情人节", "solar", (2, 14)),
    ("womens_day", "妇女节", "solar", (3, 8)),
    ("arbor_day", "植树节", "solar", (3, 12)),
    ("qingming", "清明节", "solar_term", "ChingMing"),
    ("easter", "复活节", "solar", "Easter"),
    ("labor_day", "劳动节", "solar", (5, 1)),
    ("mothers_day", "母亲节", "solar", (5, 6, 2)),
    ("childrens_day", "儿童节", "solar", (6, 1)),
    ("dragon_boat", "端午节", "lunar", "DragonBoat"),
    ("fathers_day", "父亲节", "solar", (6, 6, 3)),
    ("qixi", "七夕节", "lunar", "Qixi"),
    ("teachers_day", "教师节", "solar", (9, 10)),
    ("mid_autumn", "中秋节", "lunar", "MidAutumn"),
    ("national_day", "国庆节", "solar", (10, 1)),
    ("double_ninth", "重阳节", "lunar", "ChongYang"),
    ("halloween", "万圣夜", "solar", (10, 31)),
    ("thanksgiving", "感恩节（美国）", "solar", (11, 3, 4)),
    ("winter_solstice", "冬至", "solar_term", "DongJie"),
    ("christmas_eve", "平安夜", "solar", (12, 24)),
    ("christmas", "圣诞节", "solar", (12, 25)),
)


def special_holiday_catalog() -> list[dict[str, Any]]:
    """Expose optional date support without substituting approximate dates."""
    return [dict(id=key, name=name, calendar=calendar,
                 available=isinstance(rule, tuple) or callable(getattr(_special_lunar_festival, rule, None)))
            for key, name, calendar, rule in _SPECIAL_HOLIDAYS]


def special_settings_defaults() -> dict[str, Any]:
    return {
        "birthday_profile": {},
        "holiday_messages": {"enabled": False, "holidays": [], "start_time": "10:00", "end_time": "20:30"},
        "course_timetable": {
            "enabled": False, "anchor_date": "", "anchor_week": 1, "anchor_confirmed": False,
            "timezone": _SPECIAL_TIMEZONE, "remind_minutes": 10, "quiet_during_class": True,
            "periods": [], "courses": [], "exceptions": [],
        },
    }


def _special_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) - fields:
        raise ValueError(f"{label}字段无效")
    return value


def _special_text(value: Any, label: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label}无效")
    value = value.strip()
    if not empty and not value:
        raise ValueError(f"{label}不能为空")
    return value


def _special_integer(value: Any, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}须为{low}至{high}之间的整数")
    return value


def _special_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label}须为开关")
    return value


def _special_time(value: Any, label: str) -> str:
    value = _special_text(value, label, 5)
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError(f"{label}须为有效的HH:MM时间")
    return value


def _special_source(raw: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if "source" in raw:
        result["source"] = _special_text(raw["source"], "资料来源", 80, empty=True)
    return result


def _special_birthday(raw: Any) -> dict[str, Any]:
    raw = _special_object(raw, {"calendar", "month", "day", "source"}, "生日")
    if not raw:
        return {}
    if raw.get("calendar", "solar") != "solar":
        raise ValueError("生日目前仅支持公历")
    month = _special_integer(raw.get("month"), "生日月份", 1, 12)
    day = _special_integer(raw.get("day"), "生日日期", 1, 31)
    try:
        date(2000, month, day)
    except ValueError as exc:
        raise ValueError("生日不是有效的公历月日") from exc
    return _special_source(raw, dict(calendar="solar", month=month, day=day))


def _special_holiday_settings(raw: Any) -> dict[str, Any]:
    defaults = special_settings_defaults()["holiday_messages"]
    raw = _special_object(raw, set(defaults) | {"source"}, "节日主动消息")
    result = dict(defaults, **raw)
    result["enabled"] = _special_bool(result["enabled"], "节日主动消息")
    selected = result["holidays"]
    known = {entry[0] for entry in _SPECIAL_HOLIDAYS}
    if (type(selected) is not list or len(selected) > len(known)
            or any(type(item) is not str or item not in known for item in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError("节日列表须为不重复的内置节日编号")
    result["holidays"] = list(selected)
    result["start_time"] = _special_time(result["start_time"], "节日发送开始时间")
    result["end_time"] = _special_time(result["end_time"], "节日发送结束时间")
    if result["start_time"] >= result["end_time"]:
        raise ValueError("节日发送结束时间须晚于开始时间，不能跨日")
    return _special_source(raw, result)


def _special_course_week(course: dict[str, Any], day: date, anchor: date, anchor_week: int) -> int | None:
    week = anchor_week + (day - anchor).days // 7
    if (not 1 <= week <= 53 or course["weekday"] != day.isoweekday()
            or not course["week_start"] <= week <= course["week_end"]
            or course["parity"] == "odd" and week % 2 != 1
            or course["parity"] == "even" and week % 2 != 0):
        return None
    return week


def _special_course_date(raw: Any, label: str) -> date:
    value = _special_text(raw, label, 10)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}须为YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label}须为YYYY-MM-DD")
    return parsed


def _special_course_datetime(raw: Any, label: str) -> datetime:
    value = _special_text(raw, label, 16)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
        raise ValueError(f"{label}须为北京时间YYYY-MM-DDTHH:MM")
    try:
        return datetime.fromisoformat(value).replace(tzinfo=zoneinfo.ZoneInfo(_SPECIAL_TIMEZONE))
    except ValueError as exc:
        raise ValueError(f"{label}不是有效日期时间") from exc


def _special_course_exceptions(raw: Any, courses: list[dict[str, Any]], anchor_date: str,
                               anchor_week: int) -> list[dict[str, Any]]:
    if type(raw) is not list or len(raw) > 200:
        raise ValueError("单次停课或调课最多200项")
    if raw and not anchor_date:
        raise ValueError("填写单次停课或调课前须设置教学周锚点")
    anchor = date.fromisoformat(anchor_date) if anchor_date else None
    by_id, identities, occurrences, result = {item["id"]: item for item in courses}, set(), set(), []
    for item in raw:
        item = _special_object(item, {"id", "course_id", "date", "action", "new_start", "new_end", "location", "note", "source"}, "单次课表例外")
        identity = _special_text(item.get("id"), "例外编号", 64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identity) or identity in identities:
            raise ValueError("例外编号须为不重复的字母数字、点、短横线或下划线")
        course_id = _special_text(item.get("course_id"), "原课程编号", 64)
        course = by_id.get(course_id)
        if course is None:
            raise ValueError("单次例外引用的课程不存在；删除课程前请先移除其例外")
        original_day = _special_course_date(item.get("date"), "原上课日期")
        if _special_course_week(course, original_day, anchor, anchor_week) is None:
            raise ValueError("原上课日期不符合该课程的星期、教学周或单双周安排")
        occurrence = (course_id, original_day.isoformat())
        if occurrence in occurrences:
            raise ValueError("同一课程同一原日期只能设置一项停课或调课")
        action = item.get("action")
        if action not in ("cancel", "reschedule"):
            raise ValueError("单次例外须选择停课或调课")
        normalized = dict(id=identity, course_id=course_id, date=original_day.isoformat(), action=action,
                          note=_special_text(item.get("note", ""), "调课说明", 240, empty=True))
        if action == "cancel":
            if any(key in item for key in ("new_start", "new_end", "location")):
                raise ValueError("停课不能同时填写新的上课时间或地点")
        else:
            start = _special_course_datetime(item.get("new_start"), "调课开始时间")
            end = _special_course_datetime(item.get("new_end"), "调课结束时间")
            if start.date() != end.date() or start >= end:
                raise ValueError("调课起止须在同一天，结束时间晚于开始时间")
            if abs((start.date() - original_day).days) > 366:
                raise ValueError("调课日期须在原日期前后366天内")
            normalized.update(new_start=start.replace(tzinfo=None).isoformat(timespec="minutes"),
                              new_end=end.replace(tzinfo=None).isoformat(timespec="minutes"),
                              location=_special_text(item.get("location", course["location"]), "调课地点", 120, empty=True))
        identities.add(identity); occurrences.add(occurrence)
        result.append(_special_source(item, normalized))
    return result


def _special_course_settings(raw: Any) -> dict[str, Any]:
    defaults = special_settings_defaults()["course_timetable"]
    raw = _special_object(raw, set(defaults) | {"source"}, "课表")
    result = dict(defaults, **raw)
    for key, label in (("enabled", "课表"), ("anchor_confirmed", "周次已确认"),
                       ("quiet_during_class", "上课免打扰")):
        result[key] = _special_bool(result[key], label)
    if result["timezone"] != _SPECIAL_TIMEZONE:
        raise ValueError("课表时区仅支持Asia/Shanghai")
    result["anchor_week"] = _special_integer(result["anchor_week"], "锚点周次", 1, 53)
    result["remind_minutes"] = _special_integer(result["remind_minutes"], "课前提醒分钟数", 0, 120)
    result["anchor_date"] = _special_text(result["anchor_date"], "锚点日期", 10, empty=True)
    if result["anchor_date"]:
        try:
            anchor = date.fromisoformat(result["anchor_date"])
        except ValueError as exc:
            raise ValueError("锚点日期须为YYYY-MM-DD") from exc
        if anchor.isoformat() != result["anchor_date"] or anchor.weekday() != 0:
            raise ValueError("锚点日期须为对应教学周的星期一")
    elif result["enabled"] or result["anchor_confirmed"]:
        raise ValueError("启用或确认课表前须填写星期一锚点日期")
    periods, courses = result["periods"], result["courses"]
    if type(periods) is not list or len(periods) > 24:
        raise ValueError("每日节次最多24项")
    if type(courses) is not list or len(courses) > 60:
        raise ValueError("课程最多60项")
    normalized_periods, ids = [], set()
    for item in periods:
        item = _special_object(item, {"id", "start", "end", "source"}, "节次")
        identity = _special_integer(item.get("id"), "节次编号", 1, 24)
        start = _special_time(item.get("start"), "节次开始时间")
        end = _special_time(item.get("end"), "节次结束时间")
        if identity in ids or start >= end:
            raise ValueError("节次编号不能重复，结束时间须晚于开始时间")
        ids.add(identity)
        normalized_periods.append(_special_source(item, dict(id=identity, start=start, end=end)))
    normalized_periods.sort(key=lambda item: item["id"])
    if any(left["end"] > right["start"] for left, right in zip(normalized_periods, normalized_periods[1:])):
        raise ValueError("节次须按编号依次排列，时间不能重叠或倒序")
    normalized_courses, course_ids = [], set()
    fields = {"id", "name", "weekday", "start_period", "end_period", "week_start", "week_end", "parity", "location", "source"}
    for item in courses:
        item = _special_object(item, fields, "课程")
        identity = _special_text(item.get("id"), "课程编号", 64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identity) or identity in course_ids:
            raise ValueError("课程编号须为不重复的字母数字、点、短横线或下划线")
        course_ids.add(identity)
        course = dict(id=identity, name=_special_text(item.get("name"), "课程名称", 80),
                      weekday=_special_integer(item.get("weekday"), "课程星期", 1, 7),
                      start_period=_special_integer(item.get("start_period"), "开始节次", 1, 24),
                      end_period=_special_integer(item.get("end_period"), "结束节次", 1, 24),
                      week_start=_special_integer(item.get("week_start", 1), "起始教学周", 1, 53),
                      week_end=_special_integer(item.get("week_end", 53), "结束教学周", 1, 53),
                      parity=item.get("parity", "all"),
                      location=_special_text(item.get("location", ""), "上课地点", 120, empty=True))
        if (course["start_period"] > course["end_period"] or course["week_start"] > course["week_end"]
                or any(period not in ids for period in range(course["start_period"], course["end_period"] + 1))):
            raise ValueError("课程节次或教学周范围无效，请先完整填写对应节次")
        if course["parity"] not in ("all", "odd", "even"):
            raise ValueError("课程单双周须为all、odd或even")
        normalized_courses.append(_special_source(item, course))
    if result["enabled"] and (not normalized_periods or not normalized_courses):
        raise ValueError("启用课表前须填写节次和课程")
    result["periods"], result["courses"] = normalized_periods, normalized_courses
    result["exceptions"] = _special_course_exceptions(result["exceptions"], normalized_courses,
                                                      result["anchor_date"], result["anchor_week"])
    return _special_source(raw, result)


def validate_special_changes(changes: Any) -> dict[str, Any]:
    """Validate partial top-level replacement; never mutate the caller's data."""
    fields = {"birthday_profile", "holiday_messages", "course_timetable"}
    changes = _special_object(changes, fields, "节日生日与课表设置")
    if not changes:
        raise ValueError("请选择要修改的设置")
    validators = {"birthday_profile": _special_birthday, "holiday_messages": _special_holiday_settings,
                  "course_timetable": _special_course_settings}
    return {key: validators[key](value) for key, value in changes.items()}


def _special_local_now(now_ts: Any) -> datetime:
    if type(now_ts) not in (int, float) or not math.isfinite(now_ts):
        raise ValueError("需要有效的当前时间戳")
    return datetime.fromtimestamp(now_ts, zoneinfo.ZoneInfo(_SPECIAL_TIMEZONE))


def _special_at(day: date, clock: str, tzinfo: Any) -> float:
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tzinfo).timestamp()


def special_calendar(user: Any, now_ts: float) -> dict[str, Any]:
    """Project today through day +14 from an explicit academic-week anchor."""
    result = dict(items=[], exception_preview=[], current_week=None, anchor_confirmed=False,
                  timezone=_SPECIAL_TIMEZONE, calendar_available=True)
    try:
        current = _special_local_now(now_ts)
        raw = user.get("course_timetable", {}) if isinstance(user, dict) else {}
        settings = _special_course_settings(raw)
    except (TypeError, ValueError, KeyError, OverflowError, OSError):
        result["calendar_available"] = False
        return result
    result["anchor_confirmed"] = settings["anchor_confirmed"]
    if not settings["anchor_date"]:
        return result
    anchor = date.fromisoformat(settings["anchor_date"])
    today = current.date()
    result["current_week"] = settings["anchor_week"] + (today - anchor).days // 7
    if not settings["enabled"]:
        return result
    periods = {item["id"]: item for item in settings["periods"]}
    exceptions = {(item["course_id"], item["date"]): item for item in settings["exceptions"]}
    by_id = {item["id"]: item for item in settings["courses"]}
    last_day, projected = today + timedelta(days=14), {}

    def project(course: dict[str, Any], original_day: date) -> None:
        week = _special_course_week(course, original_day, anchor, settings["anchor_week"])
        if week is None:
            return
        original_date = original_day.isoformat()
        adjustment = exceptions.get((course["id"], original_date))
        start = _special_at(original_day, periods[course["start_period"]]["start"], current.tzinfo)
        end = _special_at(original_day, periods[course["end_period"]]["end"], current.tzinfo)
        actual_day, location = original_day, course["location"]
        if adjustment:
            if adjustment["action"] == "cancel":
                if today <= original_day <= last_day:
                    result["exception_preview"].append(dict(id=adjustment["id"], action="cancel",
                        course_id=course["id"], name=course["name"], original_date=original_date,
                        note=adjustment["note"]))
                return
            new_start = _special_course_datetime(adjustment["new_start"], "调课开始时间")
            start = new_start.timestamp()
            end = _special_course_datetime(adjustment["new_end"], "调课结束时间").timestamp()
            actual_day, location = new_start.date(), adjustment["location"]
        if not today <= actual_day <= last_day:
            return
        identity = f"{course['id']}:{original_date}"
        item = dict(id=identity, name=course["name"], location=location, start_at=start, end_at=end,
                    date=actual_day.isoformat(), week=week, weekday=actual_day.isoweekday(),
                    source="course_timetable", editable=False)
        if adjustment:
            item.update(original_date=original_date, exception_id=adjustment["id"],
                        adjustment="reschedule", adjustment_note=adjustment["note"])
            if identity not in projected:
                result["exception_preview"].append(dict(id=adjustment["id"], action="reschedule",
                    course_id=course["id"], name=course["name"], original_date=original_date,
                    date=item["date"], start_at=start, end_at=end, location=location, note=adjustment["note"]))
        projected[identity] = item

    for offset in range(15):
        day = today + timedelta(days=offset)
        for course in settings["courses"]:
            project(course, day)
    # An original occurrence outside the visible fortnight may be moved into
    # it. Keep the original identity, so edits never create a second reminder.
    for adjustment in settings["exceptions"]:
        if adjustment["action"] == "reschedule":
            project(by_id[adjustment["course_id"]], date.fromisoformat(adjustment["date"]))
    result["items"] = list(projected.values())
    result["items"].sort(key=lambda item: (item["start_at"], item["end_at"], item["id"]))
    result["exception_preview"].sort(key=lambda item: (item.get("date", item["original_date"]), item["course_id"]))
    return result


def _special_holiday_dates(rule: Any, year: int) -> set[date]:
    if isinstance(rule, tuple):
        if len(rule) == 2:
            return {date(year, rule[0], rule[1])}
        month, weekday, ordinal = rule
        first = date(year, month, 1)
        return {first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (ordinal - 1))}
    helper = getattr(_special_lunar_festival, rule, None)
    if not callable(helper):
        return set()
    found = set()
    # Winter lunar festivals can fall in either adjacent Gregorian year.
    for festival_year in (year - 1, year, year + 1):
        try:
            value = helper(festival_year)
            if isinstance(value, datetime):
                value = value.date()
            if isinstance(value, date) and value.year == year:
                found.add(value)
        except Exception:
            continue
    return found


def special_day_events(user: Any, now_ts: float) -> list[dict[str, Any]]:
    """Resolve actual observance dates, never vacation ranges or guesses."""
    if not isinstance(user, dict):
        return []
    try:
        current = _special_local_now(now_ts)
    except (TypeError, ValueError, KeyError, OverflowError, OSError):
        return []
    today, events = current.date(), []

    def add(identity: str, name: str, kind: str, start: str = "10:00", end: str = "20:30") -> None:
        date_text = today.isoformat()
        event_key = f"{kind}:{identity}:{date_text}"
        context = dict(observance_date=date_text, observance_year=today.year, event_key=event_key,
                       holiday_id=identity, holiday_name=name, kind=kind, timezone=_SPECIAL_TIMEZONE,
                       start_time=start, end_time=end)
        events.append(dict(id=identity, name=name, date=date_text, event_key=event_key, context=context, kind=kind))

    profile = user.get("birthday_profile")
    if isinstance(profile, dict):
        try:
            birthday = _special_birthday({key: profile[key] for key in ("calendar", "month", "day", "source") if key in profile})
        except ValueError:
            birthday = {}
        if (birthday and birthday["month"] == today.month and birthday["day"] == today.day
                and not bool(user.get("birthday_celebration_opt_out", False))):
            add("birthday", "生日", "birthday")
    try:
        holidays = _special_holiday_settings(user.get("holiday_messages", {}))
    except ValueError:
        return events
    if holidays["enabled"]:
        selected = set(holidays["holidays"])
        for identity, name, _calendar, rule in _SPECIAL_HOLIDAYS:
            if identity in selected and today in _special_holiday_dates(rule, today.year):
                add(identity, name, "holiday", holidays["start_time"], holidays["end_time"])
    return events


def course_quiet_until(user: Any, now_ts: float) -> float:
    """Return the end of a current course block, without scheduling anything."""
    if not isinstance(user, dict):
        return 0.0
    try:
        settings = _special_course_settings(user.get("course_timetable", {}))
    except ValueError:
        return 0.0
    if not settings["enabled"] or not settings["quiet_during_class"]:
        return 0.0
    calendar = special_calendar(user, now_ts)
    return max((item["end_at"] for item in calendar["items"]
                if item["start_at"] <= now_ts < item["end_at"]), default=0.0)

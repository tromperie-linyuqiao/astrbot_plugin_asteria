# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from astrbot.api import logger
from ..astrbot_knowledge_reader import AstrBotKnowledgeReader

from .helpers import _single_line


class AstrBotKnowledgeMixin:
    """Read AstrBot knowledge-base metadata and selected chunks for roleplay context."""

    @staticmethod
    def _normalize_roleplay_knowledge_source_ids(value: Any, *, limit: int = 80) -> list[str]:
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, tuple):
            raw_items = list(value)
        else:
            raw = str(value or "")
            raw_items = re.split(r"[\r\n,，;；]+", raw)
        ids: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item or "").strip()
            if not text or len(text) > 260:
                continue
            if not (text.startswith("kb:") or text.startswith("doc:")):
                continue
            if text in seen:
                continue
            seen.add(text)
            ids.append(text)
            if len(ids) >= limit:
                break
        return ids

    async def _astrbot_knowledge_sources(self) -> list[dict[str, Any]]:
        reader = AstrBotKnowledgeReader(self.context)
        items = []
        try:
            async with asyncio.timeout(8):
                for base in (await reader.bases())[:30]:
                    kb_id = base.kb_id
                    helper = await reader.base(kb_id)
                    if helper is None:
                        continue
                    documents = [
                        dict(id=f"doc:{kb_id}:{doc.doc_id}", type="document", kb_id=kb_id,
                             doc_id=doc.doc_id, name=doc.doc_name or doc.doc_id,
                             file_type=str(doc.file_type or ""), chunk_count=int(doc.chunk_count or 0),
                             updated_at=str(doc.updated_at or ""))
                        for doc in await reader.documents(helper, limit=200)
                    ]
                    items.append(dict(id=f"kb:{kb_id}", type="knowledge_base", kb_id=kb_id,
                        name=base.kb_name or kb_id, description=base.description or "", emoji=base.emoji or "",
                        doc_count=int(base.doc_count or len(documents)), chunk_count=int(base.chunk_count or 0),
                        updated_at=str(base.updated_at or ""), documents=documents))
        except Exception as exc:
            logger.warning("[Asteria] AstrBot 知识库目录暂不可用: %s", type(exc).__name__)
            return []
        return items

    async def _roleplay_knowledge_summary(self) -> dict[str, Any]:
        selected = self._normalize_roleplay_knowledge_source_ids(
            getattr(self, "roleplay_knowledge_source_ids", [])
        )
        sources = await self._astrbot_knowledge_sources()
        available_ids = {str(item.get("id") or "") for item in sources}
        for item in sources:
            for doc in item.get("documents") or []:
                available_ids.add(str(doc.get("id") or ""))
        return {
            "available": bool(sources),
            "root": "AstrBot 知识库接口",
            "window": {"knowledge_bases": 30, "documents_per_base": 200},
            "sources": sources,
            "selected_ids": selected,
            "selected_count": len(selected),
            "missing_ids": [item for item in selected if item not in available_ids],
        }

    async def _format_roleplay_knowledge_context(
        self,
        *,
        query: str = "",
        purpose: str = "roleplay",
        max_chars: int = 3200,
        max_chunks: int = 18,
    ) -> str:
        selected = self._normalize_roleplay_knowledge_source_ids(
            getattr(self, "roleplay_knowledge_source_ids", [])
        )
        if not selected:
            return ""
        sources = await self._astrbot_knowledge_sources()
        if not sources:
            return ""

        kb_names = {str(item.get("kb_id") or ""): str(item.get("name") or "") for item in sources}
        doc_names: dict[tuple[str, str], str] = {}
        selected_kbs: set[str] = set()
        selected_docs: dict[str, set[str]] = {}
        for source in sources:
            kb_id = str(source.get("kb_id") or "")
            if f"kb:{kb_id}" in selected:
                selected_kbs.add(kb_id)
            for doc in source.get("documents") or []:
                doc_id = str(doc.get("doc_id") or "")
                doc_names[(kb_id, doc_id)] = str(doc.get("name") or doc_id)
                if str(doc.get("id") or "") in selected:
                    selected_docs.setdefault(kb_id, set()).add(doc_id)

        if not selected_kbs and not selected_docs:
            return ""

        chunk_budget = max(1, int(max_chunks or 18))
        char_budget = max(600, int(max_chars or 3200))
        candidates: list[dict[str, Any]] = []
        for kb_id in sorted(selected_kbs | set(selected_docs)):
            doc_filter = None if kb_id in selected_kbs else selected_docs.get(kb_id, set())
            remaining = min(1200, max(200, chunk_budget * 60)) - len(candidates)
            if remaining <= 0:
                break
            chunks = await self._read_roleplay_knowledge_chunks(kb_id, doc_filter, scan_limit=remaining)
            for chunk in chunks:
                doc_id = str(chunk.get("kb_doc_id") or "")
                chunk["kb_id"] = kb_id
                chunk["kb_name"] = kb_names.get(kb_id, kb_id)
                chunk["doc_name"] = doc_names.get((kb_id, doc_id), doc_id or "资料")
                candidates.append(chunk)
        if not candidates:
            return ""

        effective_query = query or self._build_roleplay_knowledge_query(purpose=purpose)
        selected_chunks = self._select_roleplay_knowledge_chunks(
            candidates,
            query=effective_query,
            max_chunks=chunk_budget,
        )
        used_search = bool(selected_chunks)
        if not selected_chunks:
            selected_chunks = self._select_representative_roleplay_chunks(candidates, max_chunks=chunk_budget)

        snippets: list[str] = []
        for chunk in selected_chunks:
            text = _single_line(chunk.get("text", ""), 700)
            if not text:
                continue
            source = f"{chunk.get('kb_name') or chunk.get('kb_id') or '知识库'} / {chunk.get('doc_name') or '资料'}"
            snippets.append(f"- {source}: {text}")
        if not snippets:
            return ""
        body = "\n".join(snippets)
        if len(body) > char_budget:
            body = body[:char_budget].rstrip() + "..."
        mode_text = "按当前用途检索匹配片段" if used_search else "未命中检索词，回退为文档代表性取样"
        return (
            "【AstrBot 知识库世界观参考】\n"
            "以下内容来自拓展页角色设定中勾选的 AstrBot 知识库/文档，只作为日程模拟、生活背景和世界观适配参考；"
            "不要复述“知识库/文档/片段”等后台来源，不要把小说叙事逐字当成当前现实发言。\n"
            f"选取方式：{mode_text}；用途：{_single_line(purpose, 40) or 'roleplay'}。\n"
            f"{body}"
        )

    def _build_roleplay_knowledge_query(self, *, purpose: str = "roleplay") -> str:
        anchors = {
            "schedule": "日程 作息 生活 学校 工作 休息 住所 城市 关系 习惯 能力 身份 当前活动",
            "worldview": "世界观 时代 背景 法则 规则 能力 种族 组织 地点 关系网 术语 现代功能转译",
        }
        purpose_key = str(purpose or "").lower()
        anchor = anchors["worldview" if "world" in purpose_key or "适配" in purpose_key else "schedule"]
        parts = [
            str(purpose or ""),
            anchor,
            getattr(self, "bot_name", ""),
            getattr(self, "schedule_persona_prompt", ""),
            getattr(self, "schedule_worldview_prompt", ""),
            getattr(self, "roleplay_user_profile_prompt", ""),
            getattr(self, "worldview_adaptation_prompt", ""),
        ]
        getter = getattr(self, "_get_default_persona_prompt", None)
        if callable(getter):
            try:
                parts.append(getter())
            except Exception:
                pass
        return "\n".join(str(part or "") for part in parts if str(part or "").strip())

    def _select_roleplay_knowledge_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        query: str,
        max_chunks: int,
    ) -> list[dict[str, Any]]:
        terms = self._roleplay_knowledge_query_terms(query)
        if not terms:
            return []

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for order, chunk in enumerate(chunks):
            text = self._knowledge_norm(chunk.get("text", ""))
            title = self._knowledge_norm(f"{chunk.get('kb_name', '')} {chunk.get('doc_name', '')}")
            if not text:
                continue
            score = 0.0
            matched = 0
            for term, weight in terms:
                text_count = text.count(term)
                title_count = title.count(term)
                if text_count or title_count:
                    matched += 1
                    score += min(text_count, 4) * weight
                    score += min(title_count, 2) * weight * 1.6
            if score <= 0:
                continue
            try:
                chunk_index = int(chunk.get("chunk_index") or 0)
            except (TypeError, ValueError):
                chunk_index = 0
            score += min(matched, 6) * 0.6
            score += max(0.0, 0.35 - min(chunk_index, 12) * 0.02)
            scored.append((score, order, chunk))
        if not scored:
            return []

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected: list[dict[str, Any]] = []
        doc_counts: dict[tuple[str, str], int] = {}
        doc_indices: dict[tuple[str, str], set[int]] = {}
        text_fingerprints: set[str] = set()
        per_doc_limit = max(2, (max_chunks + 1) // 2)
        deferred: list[dict[str, Any]] = []

        def add_chunk(chunk: dict[str, Any], *, allow_adjacent: bool) -> bool:
            doc_key = (str(chunk.get("kb_id") or ""), str(chunk.get("kb_doc_id") or ""))
            if doc_counts.get(doc_key, 0) >= per_doc_limit:
                return False
            try:
                chunk_index = int(chunk.get("chunk_index") or 0)
            except (TypeError, ValueError):
                chunk_index = 0
            if not allow_adjacent and any(abs(chunk_index - used) <= 1 for used in doc_indices.get(doc_key, set())):
                return False
            text = _single_line(chunk.get("text", ""), 220)
            fingerprint = self._knowledge_norm(text)[:160]
            if fingerprint and fingerprint in text_fingerprints:
                return False
            if fingerprint:
                text_fingerprints.add(fingerprint)
            selected.append(chunk)
            doc_counts[doc_key] = doc_counts.get(doc_key, 0) + 1
            doc_indices.setdefault(doc_key, set()).add(chunk_index)
            return True

        for _score, _order, chunk in scored:
            if not add_chunk(chunk, allow_adjacent=False):
                deferred.append(chunk)
            if len(selected) >= max_chunks:
                break
        for chunk in deferred:
            if len(selected) >= max_chunks:
                break
            add_chunk(chunk, allow_adjacent=True)
        return selected

    def _select_representative_roleplay_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        max_chunks: int,
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for chunk in chunks:
            grouped.setdefault(
                (str(chunk.get("kb_id") or ""), str(chunk.get("kb_doc_id") or "")),
                [],
            ).append(chunk)
        for items in grouped.values():
            items.sort(key=lambda item: int(item.get("chunk_index") or 0))
        selected: list[dict[str, Any]] = []
        max_len = max((len(items) for items in grouped.values()), default=0)
        for index in range(max_len):
            for key in sorted(grouped):
                items = grouped[key]
                if index < len(items):
                    selected.append(items[index])
                    if len(selected) >= max_chunks:
                        return selected
        return selected

    def _roleplay_knowledge_query_terms(self, query: str) -> list[tuple[str, float]]:
        text = self._knowledge_norm(query)
        if not text:
            return []
        raw_terms = re.findall(r"[a-z][a-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,12}", text)
        stop_terms = {
            "角色设定", "世界观", "生活背景", "其他补充", "用户补充", "当前使用",
            "日程专用", "适配模式", "自定义", "默认人格", "插件", "不要", "可以",
            "例如", "使用", "当前", "补充信息", "主要", "基本", "关系",
        }
        weighted: dict[str, float] = {}
        for raw in raw_terms:
            term = raw.strip()
            if not term or term in stop_terms:
                continue
            weight = 1.0 + min(len(term), 8) / 8.0
            weighted[term] = max(weighted.get(term, 0.0), weight)
            if re.fullmatch(r"[\u4e00-\u9fff]{5,12}", term):
                for size in (2, 3, 4):
                    for index in range(0, len(term) - size + 1):
                        sub = term[index:index + size]
                        if sub in stop_terms:
                            continue
                        weighted[sub] = max(weighted.get(sub, 0.0), 0.65 + size * 0.15)
        return sorted(weighted.items(), key=lambda item: (-item[1], item[0]))[:90]

    @staticmethod
    def _knowledge_norm(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).lower()
        return re.sub(r"\s+", "", text)

    async def _read_roleplay_knowledge_chunks(
        self, kb_id: str, doc_filter: set[str] | None, *, scan_limit: int,
    ) -> list[dict[str, Any]]:
        reader = AstrBotKnowledgeReader(self.context)
        chunks = []
        try:
            async with asyncio.timeout(8):
                helper = await reader.base(kb_id)
                if helper is None:
                    return []
                if doc_filter is None:
                    documents = await reader.documents(helper, limit=40)
                else:
                    documents = [doc for identity in sorted(doc_filter)[:40]
                                 if (doc := await helper.get_document(identity)) is not None
                                 and doc.doc_id == identity and doc.kb_id == kb_id]
                for doc in documents:
                    remaining = scan_limit - len(chunks)
                    if remaining <= 0:
                        break
                    chunks.extend(await reader.chunks(helper, doc, limit=min(100, remaining)))
        except Exception as exc:
            logger.warning("[Asteria] AstrBot 知识库片段暂不可用: %s", type(exc).__name__)
            return []
        return sorted(chunks, key=lambda row: (row["kb_doc_id"], row["chunk_index"]))

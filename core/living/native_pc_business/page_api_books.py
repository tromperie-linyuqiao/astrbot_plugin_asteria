# -*- coding: utf-8 -*-
"""Private Companion Page API - 便签/书柜(含二级认证)与世界书 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import secrets
import shutil
import sqlite3
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger
from quart import request, send_file

from .helpers import _strip_internal_message_blocks
from .memo_notes import (
    apply_memo_note_action,
    memo_note_due_state,
    memo_note_sort_key,
    normalize_memo_note,
)


class PrivateCompanionPageApiBooksMixin:
    async def unlock_bookshelf(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        password = str(payload.get("password", "")).strip()
        try:
            expected = await self.plugin._ensure_bookshelf_password_async()
            async with self.plugin._data_lock:
                if not self._bookshelf_password_matches(password, expected):
                    return self._error("密码不对。需要在聊天里自然向 Bot 询问。")
                access_token = self._issue_bookshelf_access_token()
                data = deepcopy(self.plugin.data)
            return self._ok({"bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 解锁书柜夹层失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _memo_notes_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        raw_notes = data.get("memo_notes") if isinstance(data.get("memo_notes"), list) else []
        notes = [note for note in (normalize_memo_note(item, now=now) for item in raw_notes) if note]
        notes.sort(key=lambda item: memo_note_sort_key(item, now=now))
        rows: list[dict[str, Any]] = []
        for note in notes[:200]:
            due_at = self._float(note.get("due_at"))
            due_text = ""
            due_input = ""
            if due_at > 0:
                try:
                    due_dt = self.plugin._environment_fromtimestamp(due_at)
                    due_text = due_dt.strftime("%Y-%m-%d %H:%M")
                    due_input = due_dt.strftime("%Y-%m-%dT%H:%M")
                except Exception:
                    due_text = datetime.fromtimestamp(due_at).strftime("%Y-%m-%d %H:%M")
                    due_input = datetime.fromtimestamp(due_at).strftime("%Y-%m-%dT%H:%M")
            rows.append({
                **note,
                "due_state": memo_note_due_state(note, now=now),
                "due_text": due_text,
                "due_input": due_input,
                "created_text": self.plugin._format_timestamp_elapsed(note.get("created_at", 0)),
                "updated_text": self.plugin._format_timestamp_elapsed(note.get("updated_at", 0)),
            })
        active = [item for item in rows if item.get("status") == "active"]
        return {
            "items": rows,
            "total": len(rows),
            "active": len(active),
            "completed": sum(1 for item in rows if item.get("status") == "completed"),
            "overdue": sum(1 for item in active if item.get("due_state") == "overdue"),
            "due_soon": sum(1 for item in active if item.get("due_state") in {"due", "today"}),
        }

    async def list_memo_notes(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                data = deepcopy(self.plugin.data)
            return self._ok({"memo_notes": self._memo_notes_payload(data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取备忘便签失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_memo_note(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        now = time.time()
        try:
            async with self.plugin._data_lock:
                notes, _ = apply_memo_note_action(
                    self.plugin.data.get("memo_notes"),
                    payload,
                    now=now,
                    fromtimestamp=self.plugin._environment_fromtimestamp,
                )
                self.plugin.data["memo_notes"] = notes[-200:]
                self.plugin._save_data_sync()
                result = self._memo_notes_payload(self.plugin.data)
            return self._ok({"memo_notes": result})
        except ValueError as exc:
            return self._error(str(exc))
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新备忘便签失败: {exc}", exc_info=True)
            return self._error(str(exc))

    @staticmethod
    def _normalize_bookshelf_password(value: Any) -> str:
        text = _strip_internal_message_blocks(value)
        text = re.sub(r"\s+", "", text)
        text = text.strip("「」『』“”\"'` 。，,.;；:：!！?？、~～（）()[]【】")
        return text.lower()

    def _bookshelf_password_matches(self, provided: Any, expected: Any) -> bool:
        normalized_expected = self._normalize_bookshelf_password(expected)
        normalized_provided = self._normalize_bookshelf_password(provided)
        if not normalized_expected or not normalized_provided:
            return False
        if normalized_provided == normalized_expected:
            return True
        return len(normalized_expected) >= 2 and normalized_expected in normalized_provided

    def _bookshelf_access_tokens(self) -> dict[str, float]:
        store = getattr(self.plugin, "_bookshelf_access_tokens", None)
        if not isinstance(store, dict):
            store = {}
            setattr(self.plugin, "_bookshelf_access_tokens", store)
        now = time.time()
        for token, expires_at in list(store.items()):
            if self._float(expires_at) <= now:
                store.pop(token, None)
        return store

    def _issue_bookshelf_access_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self._bookshelf_access_tokens()[token] = time.time() + 2 * 3600
        return token

    def _bookshelf_access_token_valid(self, token: Any) -> bool:
        token_text = self._single_line(token, 120)
        if not token_text:
            return False
        expires_at = self._bookshelf_access_tokens().get(token_text)
        return bool(expires_at and self._float(expires_at) > time.time())

    def _bookshelf_request_token(self, payload: dict[str, Any] | None = None) -> str:
        if isinstance(payload, dict):
            token = self._single_line(payload.get("access_token") or payload.get("token"), 120)
            if token:
                return token
        return self._single_line(request.args.get("access_token") or request.args.get("token"), 120)

    def _bookshelf_access_error(self) -> dict[str, str]:
        return {"error": "夹层访问已过期，请重新输入密码打开抽屉"}

    async def get_bookshelf_image(self):
        if not self._bookshelf_access_token_valid(self._bookshelf_request_token()):
            return self._error(self._bookshelf_access_error()["error"])
        resolved = await self._resolve_bookshelf_image_path_from_request()
        if isinstance(resolved, dict):
            return self._error(str(resolved.get("error") or "图片不存在"))
        path = resolved
        try:
            response = await send_file(path)
            response.headers["Cache-Control"] = "no-store, max-age=0"
            return response
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 读取书柜图片失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def get_bookshelf_image_data(self) -> dict[str, Any]:
        if not self._bookshelf_access_token_valid(self._bookshelf_request_token()):
            return self._error(self._bookshelf_access_error()["error"])
        resolved = await self._resolve_bookshelf_image_path_from_request()
        if isinstance(resolved, dict):
            return self._error(str(resolved.get("error") or "图片不存在"))
        path = resolved
        try:
            mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
            data = await self._read_file_base64(path)
            return self._ok(
                {
                    "mime": mime,
                    "data_url": f"data:{mime};base64,{data}",
                    "size": path.stat().st_size,
                    "mtime": int(path.stat().st_mtime),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 读取书柜图片数据失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def _read_file_base64(self, path: Path) -> str:
        import asyncio

        raw = await asyncio.to_thread(path.read_bytes)
        return base64.b64encode(raw).decode("ascii")

    async def _resolve_bookshelf_image_path_from_request(self) -> Path | dict[str, str]:
        album_id = self._single_line(request.args.get("album_id"), 40)
        page_index = self._int(request.args.get("page"))
        cover_requested = str(request.args.get("cover") or "").lower() in {"1", "true", "yes"}
        if not album_id or (page_index < 1 and not cover_requested):
            return {"error": "缺少图片参数"}
        try:
            async with self.plugin._data_lock:
                data = deepcopy(self.plugin.data)
            shelf_items = data.get("bookshelf_items") if isinstance(data.get("bookshelf_items"), list) else []
            target = None
            for item in shelf_items:
                if not isinstance(item, dict) or item.get("type") != "jm_album":
                    continue
                if self._single_line(item.get("album_id") or item.get("id"), 40) == album_id:
                    target = item
                    break
            if target is None:
                jm_state = data.get("jm_cosmos_integration") if isinstance(data.get("jm_cosmos_integration"), dict) else {}
                last_album = jm_state.get("last_album") if isinstance(jm_state.get("last_album"), dict) else {}
                if self._single_line(last_album.get("id") or last_album.get("album_id"), 40) == album_id:
                    target = last_album
            pages = target.get("pages") if isinstance(target, dict) and isinstance(target.get("pages"), list) else []
            data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
            path: Path | None = None
            if cover_requested and isinstance(target, dict):
                cover_path = self._single_line(target.get("cover_path"), 300)
                if cover_path:
                    path = Path(cover_path).resolve()
            if path is None:
                page = next((item for item in pages if isinstance(item, dict) and self._int(item.get("index")) == page_index), None)
                if cover_requested and not isinstance(page, dict):
                    page = next((item for item in pages if isinstance(item, dict) and self._int(item.get("index")) > 0), None)
                if not isinstance(page, dict):
                    return {"error": "图片不存在"}
                path = Path(str(page.get("path") or "")).resolve()
            try:
                path.relative_to(data_root)
            except ValueError:
                return {"error": "图片路径不在书柜目录内"}
            if not path.exists() or not path.is_file():
                return {"error": "图片文件不存在"}
            return path
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 读取书柜图片失败: {exc}", exc_info=True)
            return {"error": str(exc)}

    async def delete_bookshelf_item(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        access_token = self._bookshelf_request_token(payload)
        if not self._bookshelf_access_token_valid(access_token):
            return self._error(self._bookshelf_access_error()["error"])
        kind = self._single_line(payload.get("kind"), 32)
        item_id = self._single_line(payload.get("id"), 80)
        album_payload_id = self._single_line(payload.get("album_id"), 80)
        title_payload = self._single_line(payload.get("title"), 120)
        date_key = self._single_line(payload.get("date"), 32)
        try:
            async with self.plugin._data_lock:
                changed = False
                if kind == "creative":
                    projects = self.plugin.data.setdefault("creative_projects", [])
                    if not isinstance(projects, list):
                        projects = []
                    before = len(projects)
                    self.plugin.data["creative_projects"] = [
                        item
                        for item in projects
                        if not (isinstance(item, dict) and self._single_line(item.get("id"), 80) == item_id)
                    ]
                    changed = len(self.plugin.data["creative_projects"]) != before
                elif kind == "diary":
                    diaries = self.plugin.data.setdefault("bot_diaries", [])
                    if not isinstance(diaries, list):
                        diaries = []
                    before = len(diaries)
                    self.plugin.data["bot_diaries"] = [
                        item
                        for item in diaries
                        if not (isinstance(item, dict) and self._single_line(item.get("date"), 32) == date_key)
                    ]
                    changed = len(self.plugin.data["bot_diaries"]) != before
                elif kind == "jm_album":
                    album_id = album_payload_id or item_id.removeprefix("jm-")
                    album_id = album_id.removeprefix("jm-").removeprefix("jm_album:")
                    match_keys = {
                        value
                        for value in {
                            album_id,
                            item_id,
                            item_id.removeprefix("jm-"),
                            f"jm-{album_id}" if album_id else "",
                            f"jm_album:{album_id}" if album_id else "",
                        }
                        if value
                    }
                    items = self.plugin.data.setdefault("bookshelf_items", [])
                    if not isinstance(items, list):
                        items = []
                    removed_pages: list[dict[str, Any]] = []
                    removed_album_ids: set[str] = set()
                    kept = []
                    for item in items:
                        if not isinstance(item, dict) or item.get("type") != "jm_album":
                            kept.append(item)
                            continue
                        item_values = {
                            self._single_line(item.get("album_id"), 80),
                            self._single_line(item.get("id"), 80),
                            self._single_line(item.get("key"), 100),
                        }
                        title_matched = bool(title_payload and self._single_line(item.get("title"), 120) == title_payload)
                        if match_keys.intersection(value for value in item_values if value) or title_matched:
                            removed_album_id = self._single_line(item.get("album_id") or item.get("id"), 80)
                            if removed_album_id:
                                removed_album_ids.add(removed_album_id)
                            if isinstance(item.get("pages"), list):
                                removed_pages.extend(page for page in item.get("pages", []) if isinstance(page, dict))
                            changed = True
                            continue
                        kept.append(item)
                    self.plugin.data["bookshelf_items"] = kept
                    state = self.plugin.data.get("jm_cosmos_integration")
                    if isinstance(state, dict):
                        last_album = state.get("last_album")
                        last_values = {
                            self._single_line(last_album.get("id"), 80),
                            self._single_line(last_album.get("album_id"), 80),
                            self._single_line(last_album.get("key"), 100),
                        } if isinstance(last_album, dict) else set()
                        last_title_matched = bool(
                            isinstance(last_album, dict)
                            and title_payload
                            and self._single_line(last_album.get("title"), 120) == title_payload
                        )
                        if isinstance(last_album, dict) and (match_keys.intersection(value for value in last_values if value) or last_title_matched):
                            removed_album_id = self._single_line(last_album.get("id") or last_album.get("album_id"), 80)
                            if removed_album_id:
                                removed_album_ids.add(removed_album_id)
                            state["last_album"] = {}
                            changed = True
                    if not changed and album_id:
                        data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
                        if (data_root / "bookshelf_pages" / album_id).exists():
                            removed_album_ids.add(album_id)
                            changed = True
                    if removed_album_ids or title_payload:
                        state = self.plugin.data.setdefault("jm_cosmos_integration", {})
                        if not isinstance(state, dict):
                            state = {}
                            self.plugin.data["jm_cosmos_integration"] = state
                        deleted_ids = state.setdefault("deleted_album_ids", [])
                        if not isinstance(deleted_ids, list):
                            deleted_ids = []
                            state["deleted_album_ids"] = deleted_ids
                        for removed_id in sorted(removed_album_ids):
                            if removed_id and removed_id not in deleted_ids:
                                deleted_ids.append(removed_id)
                        del deleted_ids[:-300]
                        deleted_titles = state.setdefault("deleted_titles", [])
                        if not isinstance(deleted_titles, list):
                            deleted_titles = []
                            state["deleted_titles"] = deleted_titles
                        removed_titles = [
                            self._single_line(item.get("title"), 120)
                            for item in items
                            if isinstance(item, dict)
                            and item.get("type") == "jm_album"
                            and self._single_line(item.get("album_id") or item.get("id"), 80) in removed_album_ids
                        ]
                        if title_payload:
                            removed_titles.append(title_payload)
                        for removed_title in removed_titles:
                            if removed_title and removed_title not in deleted_titles:
                                deleted_titles.append(removed_title)
                        del deleted_titles[:-300]
                    self._cleanup_bookshelf_page_files(removed_pages)
                    self._cleanup_bookshelf_album_dirs(removed_album_ids)
                    logger.info(
                        "[PrivateCompanionPage] 书柜夹层移除: changed=%s id=%s album_id=%s title=%s removed=%s",
                        changed,
                        item_id,
                        album_id,
                        title_payload,
                        sorted(removed_album_ids),
                    )
                else:
                    return self._error("不支持的书柜项目类型")
                if changed:
                    self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"changed": changed, "bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 删除书柜项目失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _cleanup_bookshelf_page_files(self, pages: list[dict[str, Any]]) -> None:
        data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
        touched_dirs: set[Path] = set()
        for page in pages:
            path = Path(str(page.get("path") or "")).resolve()
            try:
                path.relative_to(data_root)
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            touched_dirs.add(path.parent)
            try:
                path.unlink()
            except Exception:
                pass
        for folder in touched_dirs:
            try:
                folder.relative_to(data_root / "bookshelf_pages")
            except ValueError:
                continue
            try:
                if folder.exists() and not any(folder.iterdir()):
                    shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass

    def _cleanup_bookshelf_album_dirs(self, album_ids: set[str]) -> None:
        if not album_ids:
            return
        data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
        page_root = data_root / "bookshelf_pages"
        for album_id in album_ids:
            safe_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(album_id or ""))
            if not safe_id:
                continue
            folder = (page_root / safe_id).resolve()
            try:
                folder.relative_to(page_root.resolve())
            except ValueError:
                continue
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass

    async def update_bookshelf_reading_state(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        access_token = self._bookshelf_request_token(payload)
        if not self._bookshelf_access_token_valid(access_token):
            return self._error(self._bookshelf_access_error()["error"])
        album_id = self._single_line(payload.get("album_id") or payload.get("id"), 32)
        page = max(1, self._int(payload.get("page")))
        total_pages = max(0, self._int(payload.get("total_pages")))
        bookmark = self._single_line(payload.get("bookmark"), 120)
        if not album_id:
            return self._error("缺少 album_id")
        try:
            async with self.plugin._data_lock:
                items = self.plugin.data.setdefault("bookshelf_items", [])
                if not isinstance(items, list):
                    items = []
                    self.plugin.data["bookshelf_items"] = items
                target = next(
                    (
                        item for item in items
                        if isinstance(item, dict)
                        and str(item.get("type") or "") == "jm_album"
                        and self._single_line(item.get("album_id") or item.get("id"), 32) == album_id
                    ),
                    None,
                )
                if target is None:
                    return self._error("没有找到这本私密阅读记录")
                safe_total = total_pages or max(0, self._int(target.get("image_count")))
                if safe_total > 0:
                    page = min(page, safe_total)
                target["reading_progress_page"] = page
                target["reading_progress_total"] = safe_total
                target["reading_progress_updated_at"] = time.time()
                target["reading_started_at"] = self._float(target.get("reading_started_at")) or time.time()
                if bookmark:
                    target["reading_bookmark"] = bookmark
                elif "bookmark" in payload:
                    target["reading_bookmark"] = ""
                if safe_total > 0 and page >= safe_total:
                    target["reading_completed_at"] = self._float(target.get("reading_completed_at")) or time.time()
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新书柜阅读进度失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def rate_bookshelf_item(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        access_token = self._bookshelf_request_token(payload)
        if not self._bookshelf_access_token_valid(access_token):
            return self._error(self._bookshelf_access_error()["error"])
        album_id = self._single_line(payload.get("album_id") or payload.get("id"), 32)
        rating = self._int(payload.get("rating"))
        reason = self._single_line(payload.get("reason"), 160)
        if not album_id:
            return self._error("缺少 album_id")
        if rating < 1 or rating > 10:
            return self._error("评分必须是 1 到 10")
        try:
            async with self.plugin._data_lock:
                items = self.plugin.data.setdefault("bookshelf_items", [])
                if not isinstance(items, list):
                    items = []
                    self.plugin.data["bookshelf_items"] = items
                target: dict[str, Any] | None = None
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "jm_album":
                        continue
                    if str(item.get("album_id") or item.get("id") or "") == album_id:
                        item["user_rating"] = rating
                        item["user_rating_reason"] = reason
                        item["user_rated_ts"] = time.time()
                        target = item
                        break
                state = self.plugin.data.setdefault("jm_cosmos_integration", {})
                if isinstance(state, dict):
                    last_album = state.get("last_album")
                    if isinstance(last_album, dict) and str(last_album.get("id") or last_album.get("album_id") or "") == album_id:
                        last_album["user_rating"] = rating
                        last_album["user_rating_reason"] = reason
                        last_album["user_rated_ts"] = time.time()
                        if target is None:
                            target = last_album
                if target is None:
                    return self._error("没有找到这条私密阅读记录")
                updater = getattr(self.plugin, "_update_private_reading_preference_profile", None)
                if callable(updater):
                    updater(target)
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 保存私密阅读评分失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _normalize_bookshelf_tag_list(self, value: Any, *, limit: int = 8) -> list[str]:
        raw_items: list[Any]
        if isinstance(value, str):
            raw_items = re.split(r"[,，、\s\n\r]+", value)
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = []
        tags: list[str] = []
        seen: set[str] = set()
        for raw in raw_items:
            tag = self._single_line(raw, 24)
            if not tag:
                continue
            normalized = tag.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            tags.append(tag)
            if len(tags) >= limit:
                break
        return tags

    def _normalize_bookshelf_page_comment(self, value: Any, *, limit: int = 100) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        page_no = self._int(value.get("page"))
        comment_text = self._single_line(value.get("comment"), limit)
        if page_no <= 0 or not comment_text:
            return None
        return {
            "page": page_no,
            "comment": comment_text,
            "raw_page": self._int(value.get("raw_page")),
            "sample_order": self._int(
                value.get("sample_order")
                or value.get("sample_index")
                or value.get("reference_index")
                or value.get("image_index")
            ),
        }

    def _merge_bookshelf_page_comments(self, *sources: Any, limit: int = 24) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for source in sources:
            if not isinstance(source, list):
                continue
            for item in source:
                normalized = self._normalize_bookshelf_page_comment(item)
                if not normalized:
                    continue
                key = (normalized["page"], normalized["comment"])
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
                if len(merged) >= limit:
                    return merged
        return merged

    async def update_bookshelf_item_tags(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        access_token = self._bookshelf_request_token(payload)
        if not self._bookshelf_access_token_valid(access_token):
            return self._error(self._bookshelf_access_error()["error"])
        album_id = self._single_line(payload.get("album_id") or payload.get("id"), 32)
        liked_tags = self._normalize_bookshelf_tag_list(payload.get("liked_tags"))
        disliked_tags_raw = self._normalize_bookshelf_tag_list(payload.get("disliked_tags"))
        liked_seen = {tag.casefold() for tag in liked_tags}
        disliked_tags = [tag for tag in disliked_tags_raw if tag.casefold() not in liked_seen]
        if not album_id:
            return self._error("缺少 album_id")
        try:
            async with self.plugin._data_lock:
                items = self.plugin.data.setdefault("bookshelf_items", [])
                if not isinstance(items, list):
                    items = []
                    self.plugin.data["bookshelf_items"] = items
                target: dict[str, Any] | None = None
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "jm_album":
                        continue
                    if str(item.get("album_id") or item.get("id") or "") == album_id:
                        item["user_liked_tags"] = liked_tags
                        item["user_disliked_tags"] = disliked_tags
                        item["user_tags_updated_ts"] = time.time()
                        target = item
                        break
                state = self.plugin.data.setdefault("jm_cosmos_integration", {})
                if isinstance(state, dict):
                    last_album = state.get("last_album")
                    if isinstance(last_album, dict) and str(last_album.get("id") or last_album.get("album_id") or "") == album_id:
                        last_album["user_liked_tags"] = liked_tags
                        last_album["user_disliked_tags"] = disliked_tags
                        last_album["user_tags_updated_ts"] = time.time()
                        if target is None:
                            target = last_album
                if target is None:
                    return self._error("没有找到这条私密阅读记录")
                updater = getattr(self.plugin, "_update_private_reading_preference_profile", None)
                if callable(updater):
                    updater(target)
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 保存私密阅读标签失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _resolve_bookshelf_data_file(self, value: Any) -> Path | None:
        path_text = self._single_line(value, 500)
        if not path_text:
            return None
        data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
        try:
            raw_path = Path(path_text)
            path = raw_path.resolve() if raw_path.is_absolute() else (data_root / raw_path).resolve()
            path.relative_to(data_root)
            if path.exists() and path.is_file():
                return path
        except Exception:
            return None
        return None

    def _jm_album_comment_sample(self, item: dict[str, Any]) -> tuple[Path | None, list[Path], list[int]]:
        cover_path = self._resolve_bookshelf_data_file(item.get("cover_path"))
        pages = item.get("pages") if isinstance(item.get("pages"), list) else []
        page_by_index: dict[int, Path] = {}
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_index = self._int(page.get("index"))
            page_path = self._resolve_bookshelf_data_file(page.get("path"))
            if page_index > 0 and page_path:
                page_by_index[page_index] = page_path
        sampled_pages = [
            self._int(page)
            for page in (item.get("sampled_pages") if isinstance(item.get("sampled_pages"), list) else [])
            if self._int(page) > 0 and self._int(page) in page_by_index
        ][:5]
        if not sampled_pages:
            sampled_pages = sorted(page_by_index)[:5]
        return cover_path, [page_by_index[page] for page in sampled_pages if page in page_by_index], sampled_pages

    async def update_bookshelf_item_comments(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        access_token = self._bookshelf_request_token(payload)
        if not self._bookshelf_access_token_valid(access_token):
            return self._error(self._bookshelf_access_error()["error"])
        album_id = self._single_line(payload.get("album_id") or payload.get("id"), 32)
        if not album_id:
            return self._error("缺少 album_id")
        try:
            async with self.plugin._data_lock:
                items = self.plugin.data.get("bookshelf_items") if isinstance(self.plugin.data.get("bookshelf_items"), list) else []
                target = next(
                    (
                        item
                        for item in items
                        if isinstance(item, dict)
                        and item.get("type") == "jm_album"
                        and str(item.get("album_id") or item.get("id") or "") == album_id
                    ),
                    None,
                )
                if target is None:
                    state = self.plugin.data.get("jm_cosmos_integration") if isinstance(self.plugin.data.get("jm_cosmos_integration"), dict) else {}
                    last_album = state.get("last_album") if isinstance(state.get("last_album"), dict) else None
                    if last_album and str(last_album.get("id") or last_album.get("album_id") or "") == album_id:
                        target = last_album
                if target is None:
                    return self._error("没有找到这条私密阅读记录")
                target_snapshot = deepcopy(target)
            cover_path, page_paths, sampled_pages = self._jm_album_comment_sample(target_snapshot)
            if not page_paths:
                return self._error("没有找到可用于重读的本地图片")
            vision = getattr(self.plugin, "_call_jm_cosmos_vision", None)
            if not callable(vision):
                return self._error("当前插件版本不支持让 Bot 重读")
            vision_result = await vision(cover_path, target_snapshot, page_paths=page_paths, sampled_pages=sampled_pages)
            if not isinstance(vision_result, dict) or not (vision_result.get("impression") or vision_result.get("page_comments")):
                return self._error("这次没有生成新的读后感或批注")
            updates: dict[str, Any] = {
                "comments_updated_ts": time.time(),
                "sampled_pages": sampled_pages,
            }
            impression = self._single_line(vision_result.get("impression"), 600)
            if impression:
                updates["impression"] = impression
                updates["reading_impression"] = impression
            rating = self._int(vision_result.get("rating"))
            if 1 <= rating <= 10:
                updates["rating"] = rating
            rating_reason = self._single_line(vision_result.get("rating_reason"), 160)
            if rating_reason:
                updates["rating_reason"] = rating_reason
            preference_tags = self._normalize_bookshelf_tag_list(vision_result.get("preference_tags"))
            if preference_tags:
                updates["preference_tags"] = preference_tags
            page_comments = vision_result.get("page_comments") if isinstance(vision_result.get("page_comments"), list) else []
            normalized_comments: list[dict[str, Any]] = []
            for comment in page_comments[:8]:
                normalized = self._normalize_bookshelf_page_comment(comment, limit=80)
                if normalized:
                    normalized_comments.append(normalized)
            if normalized_comments:
                existing_comments = target_snapshot.get("page_comments") if isinstance(target_snapshot.get("page_comments"), list) else []
                previous_comments = (
                    target_snapshot.get("page_comments_previous")
                    if isinstance(target_snapshot.get("page_comments_previous"), list)
                    else []
                )
                updates["page_comments"] = self._merge_bookshelf_page_comments(
                    existing_comments,
                    normalized_comments,
                    previous_comments,
                    limit=24,
                )
                updates["page_comments_previous"] = existing_comments[:12]
            async with self.plugin._data_lock:
                items = self.plugin.data.get("bookshelf_items") if isinstance(self.plugin.data.get("bookshelf_items"), list) else []
                written = False
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "jm_album":
                        continue
                    if str(item.get("album_id") or item.get("id") or "") == album_id:
                        item.update(updates)
                        target = item
                        written = True
                        break
                state = self.plugin.data.setdefault("jm_cosmos_integration", {})
                if isinstance(state, dict):
                    last_album = state.get("last_album")
                    if isinstance(last_album, dict) and str(last_album.get("id") or last_album.get("album_id") or "") == album_id:
                        last_album.update(updates)
                        if not written:
                            target = last_album
                            written = True
                if not written:
                    return self._error("没有找到可写回的私密阅读记录")
                updater = getattr(self.plugin, "_update_private_reading_preference_profile", None)
                if callable(updater):
                    updater(target)
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"message": "Bot 已重新读过并更新读后感", "bookshelf": await self._bookshelf_summary(data, unlocked=True, access_token=access_token)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新私密阅读批注失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def import_worldbook(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                changed = bool(self.plugin._import_worldbook_entries_from_sources())
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"changed": changed, "worldbook": self._worldbook_summary(data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 导入世界书失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_worldbook_member(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        raw_user_id = self._single_line(payload.get("user_id"), 80)
        user_id = self._normalize_worldbook_member_id(raw_user_id)
        if not user_id:
            return self._error("缺少 user_id")
        try:
            async with self.plugin._data_lock:
                profiles = self.plugin.data.setdefault("worldbook_member_profiles", {})
                if not isinstance(profiles, dict):
                    profiles = {}
                    self.plugin.data["worldbook_member_profiles"] = profiles
                if payload.get("delete"):
                    deleted = self.plugin.data.setdefault("worldbook_deleted_member_ids", [])
                    if not isinstance(deleted, list):
                        deleted = []
                        self.plugin.data["worldbook_deleted_member_ids"] = deleted
                    if user_id not in deleted:
                        deleted.append(user_id)
                    changed = profiles.pop(user_id, None) is not None
                    self.plugin._save_data_sync()
                    data = deepcopy(self.plugin.data)
                    return self._ok({"changed": changed, "message": "已删除关系节点", "worldbook": self._worldbook_summary(data)})
                if not self._worldbook_member_id_valid(user_id):
                    return self._error("关系节点必须使用有效 QQ 号或 B 站外部身份键")
                linked_qq_user_id = self._single_line(
                    payload.get("linked_qq_user_id") or payload.get("bound_qq_user_id") or payload.get("qq_user_id"),
                    40,
                )
                if linked_qq_user_id and (not linked_qq_user_id.isdigit() or len(linked_qq_user_id) < 5):
                    return self._error("绑定目标必须是有效 QQ 号")
                deleted = self.plugin.data.setdefault("worldbook_deleted_member_ids", [])
                if isinstance(deleted, list) and user_id in deleted:
                    self.plugin.data["worldbook_deleted_member_ids"] = [item for item in deleted if str(item) != user_id]
                profile = profiles.get(user_id)
                if not isinstance(profile, dict):
                    profile = {
                        "user_id": user_id,
                        "name": user_id,
                        "gender": "",
                        "aliases": [],
                        "content": "",
                        "identity_note": "",
                        "boundary_note": "",
                        "important_memories": [],
                        "enabled": True,
                        "priority": 120,
                        "source_entries": ["手动维护"],
                        "observed_names": [],
                    }
                    profiles[user_id] = profile
                profile["user_id"] = user_id
                profile["identity_type"] = "qq" if user_id.isdigit() else "external"
                if "enabled" in payload:
                    profile["enabled"] = bool(payload.get("enabled"))
                if "name" in payload:
                    profile["name"] = self._single_line(payload.get("name"), 80) or user_id
                if "gender" in payload:
                    profile["gender"] = self._single_line(payload.get("gender"), 40)
                if "aliases" in payload and isinstance(payload.get("aliases"), list):
                    profile["aliases"] = [self._single_line(item, 40) for item in payload.get("aliases", []) if self._single_line(item, 40)]
                if "content" in payload:
                    profile["content"] = str(payload.get("content") or "").strip()[:2000]
                if "note" in payload:
                    profile["note"] = str(payload.get("note") or "").strip()[:2000]
                if "identity_note" in payload:
                    profile["identity_note"] = str(payload.get("identity_note") or "").strip()[:2000]
                if "boundary_note" in payload:
                    profile["boundary_note"] = str(payload.get("boundary_note") or "").strip()[:1200]
                if "important_memories" in payload:
                    profile["important_memories"] = self._normalize_important_memories(payload.get("important_memories"))
                if "accept_pending_observation_id" in payload or "reject_pending_observation_id" in payload:
                    pending = profile.get("pending_observations") if isinstance(profile.get("pending_observations"), list) else []
                    target_id = self._single_line(
                        payload.get("accept_pending_observation_id") or payload.get("reject_pending_observation_id"),
                        40,
                    )
                    kept = []
                    accepted = None
                    for item in pending:
                        if not isinstance(item, dict):
                            continue
                        if self._single_line(item.get("id"), 40) == target_id:
                            accepted = item
                            continue
                        kept.append(item)
                    profile["pending_observations"] = kept[:24]
                    if accepted and payload.get("accept_pending_observation_id"):
                        memories = self._normalize_important_memories(profile.get("important_memories"))
                        memories.insert(
                            0,
                            {
                                "title": self._single_line(accepted.get("title"), 60) or "群聊观察",
                                "content": str(accepted.get("content") or accepted.get("evidence") or "").strip()[:500],
                                "weight": self._clamp_int(accepted.get("weight"), 35, 0, 100),
                                "privacy": "internal",
                                "source": self._single_line(accepted.get("source"), 40) or "group_observation",
                                "enabled": True,
                                "updated_at": time.time(),
                            },
                        )
                        profile["important_memories"] = self._normalize_important_memories(memories)
                if "priority" in payload:
                    profile["priority"] = self._clamp_int(payload.get("priority"), 120, -1000, 10000)
                profile["manual_edit_ts"] = time.time()
                bind_result: dict[str, Any] | None = None
                if linked_qq_user_id and linked_qq_user_id != user_id:
                    bind_result = self._bind_worldbook_external_member_locked(profiles, user_id, linked_qq_user_id, profile)
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            if payload.keys() <= {"user_id", "enabled"}:
                message = "已更新关系节点状态"
            elif "important_memories" in payload and len(payload) <= 2:
                message = "已更新重要记忆"
            elif bind_result:
                message = "已绑定到 QQ 关系节点"
            else:
                message = "已保存关系节点"
            response = {"message": message, "worldbook": self._worldbook_summary(data)}
            if bind_result:
                response["bind"] = bind_result
            return self._ok(response)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新关系节点失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def get_worldbook_member_livingmemory(self) -> dict[str, Any]:
        user_id = self._normalize_worldbook_member_id(self._single_line(request.args.get("user_id"), 80))
        if not user_id:
            return self._error("缺少 user_id")
        limit = self._query_int("limit", 20, 1, 60)
        try:
            async with self.plugin._data_lock:
                profiles = self.plugin.data.get("worldbook_member_profiles") if isinstance(self.plugin.data.get("worldbook_member_profiles"), dict) else {}
                profile = profiles.get(user_id)
                if not isinstance(profile, dict):
                    return self._error("没有找到对应关系节点")
                profile_copy = deepcopy(profile)
            token_bundle = self._worldbook_member_livingmemory_tokens(user_id, profile_copy)
            tokens = token_bundle.get("tokens", [])
            db_path = self._livingmemory_db_path()
            if not db_path:
                return self._ok(
                    {
                        "available": False,
                        "user_id": user_id,
                        "tokens": tokens,
                        "items": [],
                        "total": 0,
                        "message": "未找到 LivingMemory 数据库",
                    }
                )
            items = await asyncio.to_thread(self._query_livingmemory_for_tokens, db_path, token_bundle, limit)
            return self._ok(
                {
                    "available": True,
                    "user_id": user_id,
                    "tokens": tokens,
                    "primary_tokens": token_bundle.get("primary_tokens", []),
                    "support_tokens": token_bundle.get("support_tokens", []),
                    "items": items,
                    "total": len(items),
                    "filter_note": "默认仅召回命中 QQ 或绑定身份键的记忆；名称、别名和群名片不单独作为召回依据。",
                    "message": f"已找到 {len(items)} 条 LivingMemory 相关记忆",
                }
            )
        except sqlite3.OperationalError as exc:
            logger.warning(f"[PrivateCompanionPage] 查询 LivingMemory 失败: {exc}")
            return self._error(f"LivingMemory 数据库暂时不可读：{exc}")
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 查询关系节点 LivingMemory 失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def clear_worldbook_pending_observations(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        user_id = self._single_line(payload.get("user_id"), 40)
        try:
            async with self.plugin._data_lock:
                profiles = self.plugin.data.setdefault("worldbook_member_profiles", {})
                if not isinstance(profiles, dict):
                    profiles = {}
                    self.plugin.data["worldbook_member_profiles"] = profiles
                cleared = 0
                touched = 0
                for profile_id, profile in profiles.items():
                    if user_id and str(profile_id) != user_id:
                        continue
                    if not isinstance(profile, dict):
                        continue
                    pending = profile.get("pending_observations")
                    if not isinstance(pending, list) or not pending:
                        continue
                    cleared += len([item for item in pending if isinstance(item, dict)])
                    profile["pending_observations"] = []
                    profile["pending_observations_cleared_at"] = time.time()
                    touched += 1
                if user_id and not touched:
                    return self._error("没有找到可清理的待确认观察")
                if touched:
                    self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            message = f"已清理 {cleared} 条待确认观察" if cleared else "没有待确认观察需要清理"
            return self._ok({"message": message, "cleared": cleared, "worldbook": self._worldbook_summary(data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 清理待确认观察失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_worldbook_group(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        group_id = self._single_line(payload.get("group_id"), 40)
        if not group_id:
            return self._error("缺少 group_id")
        try:
            async with self.plugin._data_lock:
                groups = self.plugin.data.setdefault("worldbook_group_profiles", {})
                if not isinstance(groups, dict):
                    groups = {}
                    self.plugin.data["worldbook_group_profiles"] = groups
                if payload.get("delete"):
                    deleted = self.plugin.data.setdefault("worldbook_deleted_group_ids", [])
                    if not isinstance(deleted, list):
                        deleted = []
                        self.plugin.data["worldbook_deleted_group_ids"] = deleted
                    if group_id not in deleted:
                        deleted.append(group_id)
                    changed = groups.pop(group_id, None) is not None
                    self.plugin._save_data_sync()
                    data = deepcopy(self.plugin.data)
                    return self._ok({"changed": changed, "message": "已删除群资料", "worldbook": self._worldbook_summary(data)})
                deleted = self.plugin.data.setdefault("worldbook_deleted_group_ids", [])
                if isinstance(deleted, list) and group_id in deleted:
                    self.plugin.data["worldbook_deleted_group_ids"] = [item for item in deleted if str(item) != group_id]
                group = groups.get(group_id)
                if not isinstance(group, dict):
                    group = {
                        "group_id": group_id,
                        "name": group_id,
                        "content": "",
                        "enabled": True,
                        "priority": 110,
                        "aliases": [],
                        "source_entries": ["手动维护"],
                    }
                    groups[group_id] = group
                group["group_id"] = group_id
                if "enabled" in payload:
                    group["enabled"] = bool(payload.get("enabled"))
                if "name" in payload:
                    group["name"] = self._single_line(payload.get("name"), 80) or group_id
                if "content" in payload:
                    group["content"] = str(payload.get("content") or "").strip()[:2000]
                if "priority" in payload:
                    group["priority"] = self._clamp_int(payload.get("priority"), 110, -1000, 10000)
                group["manual_edit_ts"] = time.time()
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"message": "已保存群资料", "worldbook": self._worldbook_summary(data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新群资料失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def apply_preset(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip()
        presets = self._presets()
        if name not in presets:
            return self._error("未知预设")
        preset = presets[name]
        try:
            for key, value in preset.get("settings", {}).items():
                self._apply_config_value(key, self._normalize_setting_value(key, value))
            for key, value in preset.get("features", {}).items():
                if key in self._allowed_feature_keys():
                    self._apply_config_value(key, self._normalize_bool_value(value))
            if any(key in self._allowed_provider_keys() for key in preset.get("settings", {})) or "provider_config_mode" in preset.get("settings", {}):
                apply_quick = getattr(self.plugin, "_apply_quick_provider_defaults", None)
                if callable(apply_quick):
                    apply_quick()
            config_saved = await self._save_config_if_possible()
            overview = await self.get_overview()
            if overview.get("success"):
                overview["data"]["preset"] = name
                overview["data"]["preset_label"] = preset.get("label", name)
                overview["data"]["config_saved"] = config_saved
            return overview
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 应用预设失败: {exc}", exc_info=True)
            return self._error(str(exc))

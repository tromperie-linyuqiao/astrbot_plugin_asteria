"""Read AstrBot knowledge metadata and stored chunks without reaching into storage."""
from __future__ import annotations

import asyncio


class KnowledgeReadUnavailable(RuntimeError):
    pass


class AstrBotKnowledgeReader:
    def __init__(self, context):
        self.manager = getattr(context, 'kb_manager', None)

    async def bases(self):
        try:
            async with asyncio.timeout(6):
                values = await self.manager.list_kbs()
        except (AttributeError, RuntimeError, OSError, TimeoutError) as exc:
            raise KnowledgeReadUnavailable('AstrBot 知识库接口不可用') from exc
        return sorted(values, key=lambda item: (str(getattr(item, 'updated_at', '')),
                                                str(getattr(item, 'kb_id', ''))), reverse=True)

    async def base(self, identity):
        try:
            helper = await self.manager.get_kb(identity)
        except (AttributeError, RuntimeError, OSError) as exc:
            raise KnowledgeReadUnavailable('AstrBot 知识库接口不可用') from exc
        if getattr(getattr(helper, 'kb', None), 'kb_id', None) != identity:
            return None
        return helper

    async def documents(self, helper, *, limit, search=None):
        rows = await helper.list_documents(offset=0, limit=limit, search=search)
        return [row for row in rows[:limit] if getattr(row, 'kb_id', None) == helper.kb.kb_id]

    async def chunks(self, helper, document, *, limit):
        if getattr(document, 'kb_id', None) != helper.kb.kb_id:
            return []
        doc = document.doc_id
        rows = await helper.get_chunks_by_doc_id(doc, offset=0, limit=limit)
        return [dict(text=row['content'], kb_doc_id=doc, chunk_index=row.get('chunk_index', 0))
                for row in rows[:limit] if (isinstance(row, dict)
                    and row.get('kb_id') == helper.kb.kb_id and row.get('doc_id') == doc
                    and isinstance(row.get('content'), str) and len(row['content']) <= 16000
                    and type(row.get('chunk_index', 0)) is int)]


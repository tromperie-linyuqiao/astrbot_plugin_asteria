"""Source-bound answers for explicit role-daily questions, not free-form rewriting.

No model, sender, storage or scheduler. The caller validates current ownership
again before using a freshly read projection in the normal SDK response flow.
"""
from __future__ import annotations

from datetime import datetime
import math
import re

from .native_important_dates import date_zone
from .chat_corpus import _trigger_text

_SUMMARY = re.compile(r'(?:你|角色).{0,12}(?:今天|今日).{0,10}(?:做过什么|做了什么|干了什么|干嘛了|有什么安排)|(?:今天|今日).{0,8}(?:你).{0,8}(?:做过什么|做了什么|干嘛了)|^(?:今天|今日)(?:你)?(?:都)?(?:做过什么|做了什么|干嘛了|有什么安排)')
_STATUS = re.compile(r'(?:完成|做完|弄完|弄好|做了|做过|进展|状态|结束).{0,10}(?:吗|了没|没有|没有呀|没|如何|怎样|怎么样|[？?])')
_READING = re.compile(r'(?:聊聊|说说|谈谈|讲讲|介绍|内容|写了什么).{0,30}(?:文章|那篇|原文)|(?:文章|那篇|原文).{0,25}(?:聊聊|说说|谈谈|讲讲|内容|写了什么)')
_READ_TITLE = re.compile(r'读|阅读|文章|书籍|资料|文档')
_CURRENT = re.compile(r'^(?:你|角色)(?:(?:现在|此刻|这会儿|目前)(?:正)?在?|正在|在)(?:干嘛|干什么|做什么|忙什么)(?:呢|呀|啊)?[?？。!！]*$')
_PERIODS = (('上午', re.compile(r'上午|早上|今早')), ('下午', re.compile(r'下午')), ('晚上', re.compile(r'晚上|今晚')))
_GENERAL_STATUS = re.compile(
    r'^(?:(?:你|角色|今天|今日|上午|早上|今早|下午|晚上|今晚)(?:的)?'
    r'|(?:那|这)(?:一)?(?:项|件)(?:的)?|(?:安排|计划|日程|活动|事情|任务)(?:的)?'
    r'|都|全部|已经|现在|目前)*'
    r'(?:完成|做完|弄完|弄好|做了|做过|进展|状态|结束)'
    r'(?:了吗|了没|没有呀|没有|没|如何|怎样|怎么样|吗|了|呢|呀|啊)*[?？。!！]*$')


def question_kind(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return None
    query = _trigger_text(query).strip()
    if re.search(r'发送|转发|发到|取消|删除|改成|修改|创建|推迟|挪到', query):
        return None
    # Do not answer the user's own activity from the role's schedule.
    if re.match(r'^\s*我', query) and '你' not in query and '角色' not in query:
        return None
    if _CURRENT.fullmatch(query):
        return 'current'
    if _READING.search(query) and re.search(r'你.{0,16}(?:读|看|阅)|角色|那篇|这篇|原文', query):
        return 'reading'
    if _SUMMARY.search(query):
        return 'summary'
    if _STATUS.search(query) and re.search(r'你|角色|那项|那件|安排|计划|上午|早上|今早|下午|晚上|今晚|今天|日程', query):
        return 'status'
    return None


def _title(item):
    value = item.get('title', '')
    return re.sub(r'[\x00-\x1f]', ' ', value).strip()[:100] if isinstance(value, str) else ''


def _state(item):
    title = '《' + _title(item) + '》'
    if _completed(item):
        return title + '有已确认完成的记录。'
    if item.get('status') == 'ongoing':
        return title + '记录为进行中，尚未确认完成。'
    if item.get('status') == 'cancelled':
        return title + '的计划已取消，不能据此判断是否做过。'
    return title + '目前只有计划，是否完成还没有确认。'


def _completed(item):
    stamp = item.get('completed_at')
    return (item.get('status') == 'completed' and type(stamp) in (int, float)
            and math.isfinite(stamp) and stamp > 0)


def _matches(query, item):
    title = _title(item)
    if not title:
        return False
    if title in query:
        return True
    # A bounded title suffix supports references such as “书柜那项”. It only
    # chooses a read-only status; ambiguous matches are shown together.
    suffix = re.sub(r'^(?:整理|阅读|完成|进行|准备|收拾|学习|观看|安排)', '', title)
    return len(suffix) >= 2 and suffix in query


def answer(facts, query):
    kind = question_kind(query)
    if kind is None:
        return None
    if not isinstance(facts, dict):
        return '这段日常目前没有读到可靠记录，还无法确认完成情况。'
    # Use the same quote/code normalization for selection as for recognition.
    query = _trigger_text(query).strip()
    schedule = facts.get('schedule', {})
    rows = [item for item in schedule.get('items', [])[:8] if isinstance(item, dict) and _title(item)]
    current = facts.get('daily_brief', {}).get('current')
    if isinstance(current, dict) and _title(current) and not any(_title(row) == _title(current) for row in rows):
        rows.insert(0, current)
    if kind == 'current':
        if isinstance(current, dict) and _title(current) and current.get('status') == 'ongoing':
            return _state(current)
        return '当前记录里没有已确认正在进行的活动，不能仅凭计划推断此刻在做什么。'
    if kind == 'reading':
        reading = [row for row in rows if _READ_TITLE.search(_title(row))]
        exact = [row for row in reading if _matches(query, row)]
        chosen = exact or reading
        if chosen:
            names = '、'.join('《' + _title(row) + '》' for row in chosen[:2])
            return names + '在当前资料里只有标题，没有正文。可以聊这个主题；具体原文需要先提供或读取，不能凭标题补出来。'
        return '当前日常里没有这篇文章的正文，不能据此讲它写了什么。你可以把想聊的那一段给我。'
    if kind == 'summary':
        confirmed = [row for row in rows if _completed(row)]
        pending = [row for row in rows if not _completed(row)]
        pieces = [_state(row) for row in confirmed[:3]]
        if not pieces:
            pieces.append('今天这份记录里还没有已确认完成的事项。')
        pieces += [_state(row) for row in pending[:2]]
    else:
        chosen = [row for row in rows if _matches(query, row)]
        general = _GENERAL_STATUS.fullmatch(re.sub(r'\s+', '', query)) is not None
        if not chosen and not general:
            return '当前可见日常里没有找到你问的这项活动，无法确认它是否完成。可以告诉我记录中的活动名称。'
        selected = chosen if chosen else rows
        periods = [name for name, pattern in _PERIODS if pattern.search(query)]
        if periods:
            zone = date_zone(schedule.get('timezone', 'UTC+08:00'))
            chosen = []
            for row in selected:
                stamp = row.get('start_at')
                if type(stamp) not in (int, float) or not math.isfinite(stamp):
                    continue
                try:
                    hour = datetime.fromtimestamp(stamp, zone).hour
                except (ValueError, OverflowError, OSError):
                    continue
                if ('上午' in periods and hour < 12 or '下午' in periods and 12 <= hour < 18
                        or '晚上' in periods and hour >= 18):
                    chosen.append(row)
            if not chosen:
                return '当前可见日常里没有找到这个时段的对应活动，无法确认完成情况。'
        else:
            chosen = selected
        if not any(_matches(query, row) for row in chosen) and re.search(r'(?:那|这)(?:一)?(?:项|件)', query) and len(chosen) > 1:
            return '当前记录里有不止一项活动，还不能确定你指的是哪一项。可以告诉我活动名称。'
        pieces = [_state(row) for row in chosen[:3]]
        if not pieces:
            pieces = ['这份日常记录里没有能确认这项活动完成情况的内容。']
    if schedule.get('omitted', 0) or len(rows) > len(pieces):
        pieces.append('这里说的是当前可见记录，不代表全部日常。')
    return ''.join(pieces)

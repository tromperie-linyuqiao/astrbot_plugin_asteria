"""An explicit model expression protocol, never a parser for parenthesized prose.

Assistant visibility is shared by rendering, request history and memory input.
Narrative actions do not enter the user's touch or real-observation pipeline.
Invalid expression envelopes remain ordinary model text.
"""
from __future__ import annotations
import json
import re

_DRAFT_TAGS = ('thinking', 'think', 'analysis', 'reasoning')
_DRAFT_OPEN = re.compile(r'^\s*<(thinking|think|analysis|reasoning)\s*>', re.I)


def visible_text(text, *, partial=False):
    """Only leading explicit draft envelopes, never prose/code/user input.

    An unfinished envelope stays hidden. Callers own role checks; original SDK
    records are retained. Partial tag prefixes are held during streaming.
    """
    if not isinstance(text, str):
        return text
    while True:
        match = _DRAFT_OPEN.match(text)
        if match is None:
            if partial and any(('<' + tag + '>').startswith(text.lstrip().lower()) for tag in _DRAFT_TAGS):
                return ''
            return text
        end = re.search(r'</' + match[1] + r'\s*>', text[match.end():], re.I)
        if end is None:
            return ''
        text = text[match.end() + end.end():].lstrip()


class ReplyPrefix:
    """A single response's prefix; released text continues as normal deltas."""
    def __init__(self):
        self.pending = ''
        self.visible = False
        self.hidden = False

    def feed(self, text):
        if self.visible:
            return text
        self.pending += text
        self.hidden = self.hidden or _DRAFT_OPEN.match(self.pending) is not None
        value = visible_text(self.pending, partial=True)
        if value:
            self.visible = True
            self.pending = ''
        return value


def visible_parts(parts):
    """Project assistant fragments, including old split sidecars, without writes."""
    if not isinstance(parts, list):
        return parts
    prefix, result = ReplyPrefix(), []
    for part in parts:
        if not isinstance(part, dict):
            result.append(part)
            continue
        if (part.get('type') in {'plain', 'speech', 'text'} and isinstance(part.get('text'), str)
                and part.get('chain_type') not in {'reasoning', 'tool_call', 'tool_call_result'}):
            value = prefix.feed(part['text'])
            if value:
                result.append(dict(part, text=value))
        elif not (part.get('source') == 'assistant_expression' and prefix.hidden and not prefix.visible):
            result.append(part)
    return result


def visible_content(content):
    if not isinstance(content, dict) or content.get('type') != 'bot':
        return content
    result = dict(content)
    for key in ('message', 'tls_parts'):
        if key in result:
            result[key] = visible_parts(result[key])
    return result


def visible_snapshot(snapshot):
    result = dict(snapshot)
    rows = []
    for record in snapshot.get('history', []):
        if isinstance(record, dict) and isinstance(record.get('content'), dict) and record['content'].get('type') == 'bot':
            record = dict(record, content=visible_content(record['content']))
            if 'tls_parts' in record:
                record['tls_parts'] = visible_parts(record['tls_parts'])
        rows.append(record)
    result['history'] = rows
    return result


def visible_contexts(contexts):
    """Request-only SDK history copy; keep roles, tools and checkpoints intact."""
    if not isinstance(contexts, list):
        return contexts
    result = []
    for record in contexts:
        if isinstance(record, dict) and record.get('role') == 'assistant':
            content = record.get('content')
            value = visible_parts(content) if isinstance(content, list) else visible_text(content)
            if value != content:
                record = dict(record, content=value)
        result.append(record)
    return result


def visible_timeline_rows(rows):
    """Bot utterance projections, never an edit to stored events or memories."""
    result = []
    for row in rows:
        if row.get('event_type') == 'bot_response':
            text = row.get('content')
            value = visible_text(text)
            if value != text:
                row = dict(row, content=value)
        result.append(row)
    return result


class ReplyProjection:
    """Use the same prefix policy for initial and resumed SDK streams."""
    def __init__(self):
        self.prefix = ReplyPrefix()

    def frame(self, frame):
        result = dict(frame)
        kind, text = frame.get('type'), frame.get('data')
        if kind == 'run_snapshot' and isinstance(text, dict):
            content = text.get('content')
            if isinstance(content, dict) and content.get('type') == 'bot':
                self.prefix = ReplyPrefix()
                for part in content.get('message', []):
                    if (isinstance(part, dict) and part.get('type') == 'plain' and isinstance(part.get('text'), str)
                            and part.get('chain_type') not in {'reasoning', 'tool_call', 'tool_call_result'}):
                        self.prefix.feed(part['text'])
                result['data'] = dict(text, content=visible_content(content))
        elif kind in {'plain', 'complete'} and isinstance(text, str) and frame.get('chain_type') not in {'reasoning', 'tool_call', 'tool_call_result'}:
            if kind == 'plain' and frame.get('streaming') is True:
                result['data'] = self.prefix.feed(text)
            else:
                result['data'] = display(text)
                self.prefix = ReplyPrefix()
        return result

PROTOCOL = ('回复使用一个JSON对象，不加代码围栏：'
    '{"tls_reply":{"schema":1,"parts":[{"type":"action","text":"角色的叙事动作"},'
    '{"type":"speech","text":"实际说的话"}]}}。'
    'parts保持自然顺序，最多16段。action只描述虚构角色动作，不是用户指令或现实观察；'
    '没有动作就只给speech。不要提供图片路径、工具调用或伪造数据；合适表情由TLS素材库选择。'
    '只有场景确实值得配图时，可以在tls_reply内另加image_request：'
    '{"purpose":"roleplay","prompt":"一段简洁的画面描述"}。purpose只能是chat、life或roleplay；'
    '这只是生图候选，图片由后台按权限、额度和服务可用性决定；不要声称图片已经生成或送达。'
    '普通问候、简单确认不提出生图候选。')

def enabled(settings):
    mode=settings.get('reply_format','auto')
    return mode=='structured' or (mode=='auto' and settings.get('mode')=='roleplay')

def parse(text):
    if not isinstance(text,str) or len(text.encode('utf8'))>65536:return None
    raw=visible_text(text).strip()
    if not raw.startswith('{'):return None
    try:value=json.loads(raw)
    except (ValueError,RecursionError):return None
    if not isinstance(value,dict)or set(value)!={'tls_reply'}:return None
    body=value['tls_reply']
    if not isinstance(body,dict)or not {'schema','parts'}<=set(body)or set(body)-{'schema','parts','image_request'}or type(body['schema'])is not int or body['schema']!=1:return None
    if 'image_request'in body and _image_request(body['image_request'])is None:return None
    parts=body['parts']
    if not isinstance(parts,list)or not 1<=len(parts)<=16:return None
    result=[];total=0
    for part in parts:
        if not isinstance(part,dict)or set(part)!={'type','text'}or not isinstance(part['type'],str)or part['type']not in {'speech','action'}:return None
        text=part['text']
        if not isinstance(text,str)or not text.strip()or any(ord(c)<32 and c not in '\n\t\r'for c in text):return None
        total+=len(text)
        if total>16000:return None
        result.append(dict(type=part['type'],text=text,source='assistant_narrative'if part['type']=='action'else'assistant_speech'))
    return result

def _image_request(value):
    if (not isinstance(value,dict)or set(value)!={'purpose','prompt'}
            or value.get('purpose')not in {'chat','life','roleplay'}
            or not isinstance(value.get('prompt'),str)or not 1<=len(value['prompt'].strip())<=1200
            or any(ord(c)<32 and c not in '\n\t'for c in value['prompt'])):return None
    return dict(purpose=value['purpose'],prompt=value['prompt'].strip())

def image_candidate(text):
    """Only a validated explicit envelope may propose a paid background image."""
    if parse(text)is None:return None
    return _image_request(json.loads(visible_text(text))['tls_reply'].get('image_request'))

def display(text):
    text=visible_text(text)
    parts=parse(text)
    if parts is None:return text
    return '\n\n'.join('（'+p['text']+'）'if p['type']=='action'else p['text']for p in parts)

"""An explicit model expression protocol, never a parser for parenthesized prose.

Only rendering is affected. Narrative actions do not enter the user's touch or
real-observation pipeline. Invalid envelopes remain ordinary model text.
"""
from __future__ import annotations
import json

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
    raw=text.strip()
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
    return _image_request(json.loads(text)['tls_reply'].get('image_request'))

def display(text):
    parts=parse(text)
    if parts is None:return text
    return '\n\n'.join('（'+p['text']+'）'if p['type']=='action'else p['text']for p in parts)

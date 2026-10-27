"""Prompt sections and ordinary clothing continuity; no model or state access."""
from __future__ import annotations
import re

_MARKER = re.compile(
    r"(?P<negative>Negative\s+prompt\s*[:：]|负向提示词\s*[:：]|负面提示词\s*[:：])"
    r"|(?P<positive>Positive\s+prompt\s*[:：]|正向提示词\s*[:：])"
    r"|(?P<addition>Scene preset:|Current selfie scene constraint:|Default selfie composition guard:"
    r"|Selfie composition guard:|Additional fixed prompt:|Requested scene:|【指定生图场景预设】)", re.I,
)
_BARE = re.compile(r"\b(?:nude|naked|topless|bottomless|unclothed)\b|\b(?:no|without)\s+(?:any\s+)?(?:clothes|clothing|outfit)\b|裸体|裸身|全裸|不穿衣服|没有穿衣服",re.I)
_PERSON = re.compile(r"\b(?:1girl|1boy|girl|woman|female|man|boy|person|character|portrait|selfie)\b|德克萨斯|角色本人|人物|人像|自拍|穿搭",re.I)
_GARMENT = re.compile(r"\b(?:(?:white|black|red|blue|pink|green|yellow|purple|brown|beige|gr[ae]y|cream)\s+){0,2}(?:apron|dress|shirt|blouse|sweater|hoodie|jacket|coat|skirt|trousers|pants|jeans|pajamas|uniform|swimsuit|bikini)\b",re.I)
_CN_GARMENT = re.compile(r"(?P<color>白色|黑色|红色|蓝色|粉色|绿色|黄色|紫色|棕色|米色|灰色)?(?P<garment>围裙|连衣裙|衬衫|毛衣|卫衣|外套|大衣|裙子|长裤|牛仔裤|睡衣|制服|泳装|泳衣)")
_CN_NAMES={'围裙':'apron','连衣裙':'dress','衬衫':'shirt','毛衣':'sweater','卫衣':'hoodie','外套':'jacket','大衣':'coat','裙子':'skirt','长裤':'trousers','牛仔裤':'jeans','睡衣':'pajamas','制服':'uniform','泳装':'swimsuit','泳衣':'swimsuit'}
_COLORS={'白色':'white','黑色':'black','红色':'red','蓝色':'blue','粉色':'pink','绿色':'green','黄色':'yellow','紫色':'purple','棕色':'brown','米色':'beige','灰色':'gray'}
_CLOTHING_NEGATIVE=('nude','naked','topless','bottomless','unclothed','missing clothes','unrequested outfit removal')

def _line(value: str) -> str:
    return re.sub(r"\s+",' ',str(value or '')).strip(' ,;.；。')

def split_photo_prompt(text: str) -> tuple[str,str]:
    """Recover labelled positive additions even after an old negative section."""
    raw=str(text or ''); positive=[];negative=[]; cursor=0; mode='positive'; label=''
    for marker in _MARKER.finditer(raw):
        chunk=_line(raw[cursor:marker.start()])
        if chunk: (negative if mode=='negative' else positive).append(label+chunk)
        mode='negative' if marker.lastgroup=='negative' else 'positive'
        label=marker.group()+ ' ' if marker.lastgroup=='addition' else ''
        cursor=marker.end()
    chunk=_line(raw[cursor:])
    if chunk: (negative if mode=='negative' else positive).append(label+chunk)
    return '; '.join(positive), ', '.join(negative)

def _unique_terms(items) -> list[str]:
    result=[];seen=set()
    for item in items:
        text=_line(item);key=text.casefold()
        if text and key not in seen: result.append(text);seen.add(key)
    return result

def _compose(positive: str, negative: str, limit: int) -> str:
    # Every normal caller uses 1800. Tiny budgets still keep well-formed labels.
    limit=max(0,int(limit));head='Positive prompt: ';mid='. Negative prompt: '
    room=limit-len(head)-len(mid)-1
    if room<=0:return ''
    neg=_line(negative)[:min(600,max(1,room//3))].rstrip(' ,;')
    pos=_line(positive)[:max(0,room-len(neg))].rstrip(' ,;')
    return head+pos+mid+neg+'.'

def merge_photo_prompt(text: str, positive_extra: str='', negative_terms=(), limit: int=1800) -> str:
    positive,negative=split_photo_prompt(text)
    extra,extra_negative=split_photo_prompt(positive_extra)
    positive='; '.join(x for x in [extra,positive] if x)
    terms=_unique_terms(list(negative_terms)+list(re.split(r'[,;；]',extra_negative))+list(re.split(r'[,;；]',negative)))
    return _compose(positive,', '.join(terms),limit)

def _garments(text: str) -> list[str]:
    def wanted(match):
        before=text[max(0,match.start()-30):match.start()]
        return not re.search(r'(?:\b(?:no|not|without|remove|avoid)\s+(?:the\s+|an?\s+)?|不要|别穿|不用|不穿|去掉)\s*$',before,flags=re.I)
    cues=[m.group().lower() for m in _GARMENT.finditer(text) if wanted(m)]
    cues.extend(' '.join(x for x in [_COLORS.get(m.group('color'),''),_CN_NAMES[m.group('garment')]] if x) for m in _CN_GARMENT.finditer(text) if wanted(m))
    return _unique_terms(cues)[:6]

def _person_present(text: str) -> bool:
    text=re.sub(r'Image style:[^;]*','',text,flags=re.I)
    for match in _PERSON.finditer(text):
        before=text[max(0,match.start()-45):match.start()]
        if re.search(r'(?:\b(?:no|not|without|avoid|exclude)\s+(?:(?:add|adding|include|any|the|a|an)\s+)*|不要|没有|无人|别画|不画|不含)(?:任何|一个)?\s*$',before,flags=re.I):
            continue
        return True
    return False

def ensure_character_clothing(text: str, workflow_kind: str, *, clothing_hint: str='', request_text: str='', limit: int=1800) -> str:
    positive,negative=split_photo_prompt(text)
    character=str(workflow_kind or '').lower() in {'selfie','portrait','avatar','sticker','自拍','人像','头像','贴纸','表情包'} or _person_present(positive+' '+request_text)
    if not character:
        request_positive=split_photo_prompt(request_text)[0]
        extra='Requested scene: '+request_positive[:500] if request_positive else ''
        return merge_photo_prompt(text,positive_extra=extra,limit=limit)
    # Detect garment cues before removing accidental undressed tags. The apron
    # is a concrete garment; a bare tag never authorizes dropping it.
    garments=_garments(request_text) or _garments(positive)
    apron=any('apron' in cue for cue in garments)
    cleaned=_BARE.sub('',positive)
    cleaned=re.sub(r'\bonly\s+(?:an?\s+)?apron\b','apron',cleaned,flags=re.I)
    cleaned=re.sub(r'裸体围裙|裸围裙','围裙',cleaned)
    cleaned=re.sub(r'[,;]\s*[,;]+',',',cleaned)
    # Reapplying is idempotent; no accumulating policy text in a retry.
    cleaned=re.sub(r'Clothing continuity:.*?(?:;|$)','',cleaned,flags=re.I)
    hint=_line(_BARE.sub('',split_photo_prompt(clothing_hint)[0]))[:180]
    details=', '.join(garments) or hint or 'a complete everyday outfit appropriate to the scene'
    guard=('Clothing continuity: wearing '+details+
           ', complete opaque everyday outfit, covered torso and hips, visibly clothed, '
           'keep the specified garments and existing outfit')
    if apron:guard+=', visible apron retained over a covering outfit'
    terms=_unique_terms(list(_CLOTHING_NEGATIVE)+re.split(r'[,;；]',negative))
    request_positive=_line(_BARE.sub('',split_photo_prompt(request_text)[0]))[:500]
    requested='; Requested scene: '+request_positive if request_positive else ''
    return _compose(guard+requested+'; '+_line(cleaned),', '.join(terms),limit)

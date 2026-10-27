"""Editable, deterministic app-entry message data; no model, network or sends.

Only DEFAULT_APP_GREETINGS and GREETING_HOUR_GATES data were copied from the
audited phone formatter.py (SHA256 below). The separate native catalog extends
those literal prefixes to 100 messages per app. No old business is imported.
The host passes existing config/custom/surprises explicitly and persists
``export()['config']`` through its existing configuration owner. This module
opens no second store. Configuration revisions are content digests, so CAS
remains meaningful when an exported configuration is reopened.
"""
from __future__ import annotations

import hashlib
import json
import re

from .journal import JournalConflict
from .models import canonical, plain

LEGACY_DATA_SOURCE = 'astrbot_plugin_phone_perception/formatter.py'
LEGACY_DATA_SHA256 = '8e3378e4a2f00e360b3db485e7b31c2b3130fd0c1cbd3f35f8b018d597432cfe'
SCHEMA = 'tls.phone.messages.v1'
DEFAULT_APP_GREETINGS = {
    'com.hypergryph.arknights': (
        '又回罗德岛了。替我看看那边的大家。', '去看老同事了？帮我跟凯尔希问好。',
        '作战的时候别走神。', '基建的贸易站排班排好了再下线。', '这期卡池别上头，抽不到就算了。',
        '代理指挥挂完就去睡，别盯着看。', '剿灭打完了吗？打完就歇会儿。', '罗德岛的走廊还是那么长吧。',
        '今天危机合约几层？量力而行。', '又是整合运动找麻烦？替我揍他们。'),
    'com.hypergryph.arknights.bilibili': (
        '又回罗德岛了。替我看看那边的大家。', '去看老同事了？帮我跟凯尔希问好。', '作战的时候别走神。',
        '这期卡池别上头，抽不到就算了。', '代理指挥挂完就去睡，别盯着看。',
        '剿灭打完了吗？打完就歇会儿。', '又是整合运动找麻烦？替我揍他们。'),
    'com.tencent.tmgp.sgame': (
        '又要上分？这把稳着点打。', '赢了给我讲讲，输了别摔手机。', '打野别送。', '连跪三把就停，说好了。',
        'ban位给谁了？帮我看紧点。', '今晚打到星耀就收手。', '团战别第一个冲。',
        '队友吵架就屏蔽，别跟着上头。', '又在等皮肤打折？', '手机烫了就歇，别硬撑着排位。'),
    'tv.danmaku.bili': (
        '想好今晚看什么了吗？', '这个点开B站，找下饭视频还是追更？', '说个题材，我看看跟你想的是不是一路。',
        '看点轻松的就行，别又刷到半夜。', '有什么新出的纪录片吗？挑一部我们一起看。',
        '收藏夹里那几个放了很久的，今晚清一个？', '别光顾着刷推荐，你关注的那位更新了吗？',
        '看点做饭视频吧，明天学着做。', '弹幕别看太久，眼睛酸。'),
    'com.netease.cloudmusic': (
        '想听什么？说个方向，我给你攒歌单。', '今天想听点甜的，还是丧的。', '听到好听的记得推给我一首。',
        '别一个人循环到半夜。', '私人FM今天推了什么？有惊喜吗？', '这个点了，来点慢歌收收心。',
        '歌单里那首方舟曲，好久没听了吧。', '随机播放试试，说不定翻到老歌。', '音量调小点，这么晚了你。'),
}
GREETING_HOUR_GATES = {'tv.danmaku.bili': [20,5]}
APP_TAGS = {
    'com.hypergryph.arknights': ('game','arknights'),
    'com.hypergryph.arknights.bilibili': ('game','arknights'),
    'com.tencent.tmgp.sgame': ('game','moba'), 'tv.danmaku.bili': ('video',),
    'com.netease.cloudmusic': ('music',),
}
_PACKAGE = re.compile(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z')
_IDENTITY = re.compile(r'pm_[a-f0-9]{24}\Z')
_TAG = re.compile(r'[a-z0-9][a-z0-9_.-]{0,31}\Z')
_EDIT_FIELDS = {'text','tags','hours','kind','media_ref','enabled'}


class PhoneMessageConflict(JournalConflict):
    pass


def _package(value):
    if not isinstance(value,str) or len(value)>160 or not _PACKAGE.fullmatch(value):raise ValueError('invalid message app package')
    return value


def _line(value):
    if (not isinstance(value,str) or not value.strip() or len(value)>600
            or any(ord(char)<32 and char not in '\t\n\r' for char in value)):
        raise ValueError('invalid bounded phone message')
    return value  # Reviewed custom/remote wording is not rewritten or formatted.


def _hours(value):
    if value is None:return None
    if (not isinstance(value,(list,tuple)) or len(value)!=2 or any(type(x) is not int or not 0<=x<=23 for x in value)
            or value[0]==value[1]):raise ValueError('invalid message hour window')
    return list(value)


def _tags(value):
    if (not isinstance(value,(list,tuple)) or len(value)>16
            or any(not isinstance(tag,str) or not _TAG.fullmatch(tag) for tag in value)):
        raise ValueError('invalid explicit message tags')
    return sorted(set(value))


def _entry(value):
    allowed=_EDIT_FIELDS|{'id','package'}
    if not isinstance(value,dict) or set(value)-allowed or not {'package','text'}<=set(value):
        raise ValueError('invalid native message entry')
    package=_package(value['package']);text=_line(value['text']);kind=value.get('kind','text')
    if kind not in ('text','image_text'):raise ValueError('unsupported phone message kind')
    media=value.get('media_ref','')
    if not isinstance(media,str) or len(media)>256 or any(ord(char)<32 for char in media):raise ValueError('invalid media reference')
    if kind=='text' and media:raise ValueError('text message cannot conceal a media requirement')
    enabled=value.get('enabled',True)
    if type(enabled) is not bool:raise ValueError('message enabled must be boolean')
    identity=value['id'] if 'id' in value else 'pm_'+hashlib.sha256(canonical(['native',package,text,kind]).encode()).hexdigest()[:24]
    if not isinstance(identity,str) or not _IDENTITY.fullmatch(identity):raise ValueError('invalid message identity')
    return dict(id=identity,package=package,text=text,tags=_tags(value.get('tags',[])),hours=_hours(value.get('hours')),
                kind=kind,media_ref=media,enabled=enabled)


def parse_custom_lines(lines):
    """Validate legacy package|line||line configuration, retaining its wording."""
    if not isinstance(lines,(list,tuple)) or len(lines)>128:raise ValueError('bounded custom message rules required')
    result={}
    for line in lines:
        if not isinstance(line,str) or '|' not in line or len(line)>80000:raise ValueError('invalid custom message rule')
        package,rest=line.split('|',1);package=_package(package.strip())
        texts=[_line(part.strip()) for part in rest.split('||') if part.strip()]
        if not texts:raise ValueError('nonempty custom message pool required')
        pool=result.setdefault(package,[]);pool.extend(text for text in texts if text not in pool)
        if len(pool)>128:raise ValueError('bounded custom message pool required')
    return result


class NativePhoneMessages:
    """Configuration data plus pure contextual selection, with 128 rows/pool.

    Nonempty surprises replace that app's builtin/custom pool. Custom messages
    precede builtin messages. Explicit native edits overlay those rows. Recent
    messages move behind unused ones; hour/tag filtering never calls a model.
    Image-text entries require a separate media owner and block text fallback.
    Added builtin alternatives yield capacity to existing custom/native rows;
    original prefixes and user-configured text are never discarded to fit.
    """
    def __init__(self,*,custom_lines=(),surprises=None,entries=(),hour_gates=None):
        self._inputs=None;self._rows={};self.revision=''
        self.configure(custom_lines=custom_lines,surprises=surprises,entries=entries,hour_gates=hour_gates)

    def configure(self,*,custom_lines=(),surprises=None,entries=(),hour_gates=None,expected_revision=None):
        if expected_revision is not None and expected_revision!=self.revision:raise PhoneMessageConflict('message library revision changed')
        if not isinstance(custom_lines,(list,tuple)) or len(custom_lines)>128:raise ValueError('bounded custom message rules required')
        if not isinstance(entries,(list,tuple)) or len(entries)>1024:raise ValueError('bounded native message entries required')
        surprises={} if surprises is None else plain(surprises,2*1024*1024)
        greetings=surprises.get('greetings',{}) if isinstance(surprises,dict) else None
        if not isinstance(greetings,dict) or len(greetings)>128:raise ValueError('bounded surprises.greetings mapping required')
        gates=plain(GREETING_HOUR_GATES) if hour_gates is None else hour_gates
        if not isinstance(gates,dict) or len(gates)>128:raise ValueError('bounded app hour gates required')
        gates={_package(key):_hours(value) for key,value in gates.items()}
        native=[_entry(value) for value in entries]
        inputs=plain(dict(custom_lines=list(custom_lines),surprises=surprises,entries=native,hour_gates=gates),2*1024*1024)
        # The catalog imports the preserved literal prefixes from this module.
        # Load it only after module initialization; do not turn it into a remote
        # surprises override or alter exported user configuration.
        from .native_phone_message_catalog import expanded_catalog
        builtin=expanded_catalog()
        digest=hashlib.sha256(json.dumps([inputs,builtin],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if digest==self.revision:return False
        rows={};pools={};supplemental=[]
        def add(package,text,source,priority):
            package=_package(package);text=_line(text)
            identity='pm_'+hashlib.sha256(canonical([source,package,text]).encode()).hexdigest()[:24]
            if identity in rows:return identity
            rows[identity]=dict(id=identity,package=package,text=text,kind='text',media_ref='',enabled=True,
                                tags=[],hours=None,source=source,origin_source=source,priority=priority,position=len(rows))
            pools.setdefault(package,[]).append(identity)
            return identity
        for package,lines in builtin.items():
            for index,text in enumerate(lines):
                identity=add(package,text,'builtin',1)
                if index>=len(DEFAULT_APP_GREETINGS[package]):supplemental.append(identity)
        for package,texts in parse_custom_lines(custom_lines).items():
            for text in texts:add(package,text,'custom',2)
        for package,value in greetings.items():
            package=_package(package);lines=value.get('lines') if isinstance(value,dict) else value
            if not isinstance(lines,list) or len(lines)>128:raise ValueError('bounded surprise message pool required')
            if not lines:continue
            for identity in pools.pop(package,[]):rows.pop(identity)
            for text in lines:add(package,text,'surprises',3)
        for entry in native:
            previous=rows.get(entry['id'])
            if previous and previous['package']!=entry['package']:raise ValueError('message identity cannot change app')
            rows[entry['id']]=dict(entry,source='native',origin_source=previous['source'] if previous else 'native',priority=4,
                                  position=previous['position'] if previous else len(rows))
        counts={}
        for row in rows.values():counts[row['package']]=counts.get(row['package'],0)+1
        # Expansion must not invalidate an old, otherwise legal custom pool.
        # Only newly authored, unedited fallback rows can yield space. Oversize
        # user/remote/native data still fails atomically rather than truncating.
        for identity in reversed(supplemental):
            row=rows.get(identity)
            if row and row['source']=='builtin' and counts[row['package']]>128:
                rows.pop(identity);counts[row['package']]-=1
        if len(counts)>128 or any(count>128 for count in counts.values()):raise ValueError('phone message pool capacity reached')
        self._inputs,self._rows,self._gates,self.revision=inputs,rows,gates,digest
        return True

    def list(self,package=None,*,include_disabled=False):
        if package is not None:_package(package)
        if type(include_disabled) is not bool:raise ValueError('include_disabled must be boolean')
        return plain(sorted((row for row in self._rows.values() if (package is None or row['package']==package)
                            and (include_disabled or row['enabled'])),key=lambda row:(row['package'],row['position'])),2*1024*1024)

    @staticmethod
    def _in_hours(hour,window):
        return window is None or (window[0]<=hour<window[1] if window[0]<window[1] else hour>=window[0] or hour<window[1])

    def pool(self,package,*,hour,tags=(),recent=(),limit=128):
        package=_package(package)
        if type(hour) is not int or not 0<=hour<=23:raise ValueError('explicit local hour required')
        context=set(_tags(tags))|set(APP_TAGS.get(package,()))
        if (not isinstance(recent,(list,tuple)) or len(recent)>128 or any(not isinstance(x,str) for x in recent)
                or type(limit) is not int or not 1<=limit<=128):raise ValueError('bounded recent messages/limit required')
        if not self._in_hours(hour,self._gates.get(package)):return []
        rows=[row for row in self._rows.values() if row['package']==package and row['enabled']
              and self._in_hours(hour,row['hours']) and set(row['tags'])<=context]
        rows.sort(key=lambda row:(row['text'] in recent,-row['priority'],row['position']))
        return plain(rows[:limit],2*1024*1024)

    def select(self,package,*,hour,tags=(),recent=()):
        pool=self.pool(package,hour=hour,tags=tags,recent=recent,limit=1)
        message=pool[0] if pool else None
        state='media_required' if message and message['kind']=='image_text' else 'selected' if message else 'empty'
        return dict(state=state,message=message,revision=self.revision,llm_calls=0,sends=0)

    def candidate_rules(self,*,hour,tags=()):
        result={}
        for package in sorted({row['package'] for row in self._rows.values()}):
            rows=self.pool(package,hour=hour,tags=tags)
            if rows and rows[0]['kind']=='text':
                result[package]=list(dict.fromkeys(row['text'] for row in rows if row['kind']=='text'))
        return result

    def edit(self,identity,patch,*,expected_revision):
        if expected_revision!=self.revision:raise PhoneMessageConflict('message library revision changed')
        if identity not in self._rows:raise KeyError(identity)
        if not isinstance(patch,dict) or not patch or set(patch)-_EDIT_FIELDS:raise ValueError('invalid message edit fields')
        current=self._rows[identity]
        entry={key:current[key] for key in _EDIT_FIELDS|{'id','package'}};entry.update(patch);entry=_entry(entry)
        values={row['id']:row for row in self._inputs['entries']};values[identity]=entry
        config=plain(self._inputs,2*1024*1024);config['entries']=list(values.values())
        self.configure(**config,expected_revision=expected_revision)
        return plain(self._rows[identity])

    def delete(self,identity,*,expected_revision):
        return self.edit(identity,{'enabled':False},expected_revision=expected_revision)

    def export(self):
        return dict(schema=SCHEMA,revision=self.revision,config=plain(self._inputs,2*1024*1024),
                    legacy_data_source=LEGACY_DATA_SOURCE,legacy_data_sha256=LEGACY_DATA_SHA256,
                    persistent_owner='host_configuration',llm_calls=0,sends=0,network_calls=0)

    def describe(self):
        counts={}
        for row in self._rows.values():
            if row['enabled']:counts[row['package']]=counts.get(row['package'],0)+1
        return dict(schema=SCHEMA,revision=self.revision,app_counts=counts,total_messages=sum(counts.values()),
                    max_apps=128,max_pool_size=128,max_message_chars=600,host_persistence_required=True,
                    legacy_data_source=LEGACY_DATA_SOURCE,legacy_data_sha256=LEGACY_DATA_SHA256,
                    llm_calls=0,sends=0,network_calls=0)

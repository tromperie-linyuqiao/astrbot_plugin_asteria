"""Provider-independent voice direction, stored in the existing scoped Journal.

No model call, audio upload, cloning, or automatic playback. Engine bindings are
explicit; descriptive direction is never advertised as an engine capability.
"""
from copy import deepcopy
import math

NS = 'tls.voice.profile.v1'
DEFAULT = dict(name='Texas Voice · 独立音色', language='zh-CN',
    timbre='自然、清晰、克制的中文表达；不模仿原作配音演员',
    pronunciation='普通话，专有名词保持原文', emotion='平静为主，温和表达；不夸张',
    pauses='遵循原文标点，不改变动作与事实', rate=0.95, pitch=1.0,
    binding=dict(service='android_system', voice_id=''),
    rights='system_voice', test_sample='今天过得怎么样？我在这里，慢慢说就好。')


def validate(value):
    if type(value) is not dict or set(value) != set(DEFAULT):
        raise ValueError('完整声音档案字段无效')
    value = deepcopy(value)
    for key in ('name','language','timbre','pronunciation','emotion','pauses','rights','test_sample'):
        if type(value[key]) is not str or not value[key].strip() or len(value[key]) > (600 if key != 'test_sample' else 300):
            raise ValueError('声音说明过长或为空')
        value[key] = value[key].strip()
    if value['language'] not in {'zh-CN','zh-TW','en-US','ja-JP'} or value['rights'] not in {'system_voice','provider_voice'}:
        raise ValueError('声音语言或授权类型无效')
    for key, low, high in (('rate',0.7,1.3),('pitch',0.8,1.2)):
        if type(value[key]) not in (float,int) or not math.isfinite(value[key]) or not low <= value[key] <= high:
            raise ValueError('语速或音高超出支持范围')
    binding = value['binding']
    if (type(binding) is not dict or set(binding) not in ({'service','voice_id'}, {'service','voice_id','model'})
            or binding.get('service') not in {'android_system','fish_tts'} or type(binding.get('voice_id')) is not str
            or len(binding['voice_id']) > 200 or type(binding.get('model','')) is not str or len(binding.get('model','')) > 120):
        raise ValueError('音色绑定无效')
    if value['rights'] != ('system_voice' if binding['service'] == 'android_system' else 'provider_voice'):
        raise ValueError('音色来源与授权标记不一致')
    if binding['service'] == 'fish_tts' and value['pitch'] != 1:
        raise ValueError('云端音色暂不支持音高设置')
    return value


class VoiceProfile:
    def __init__(self, journal, scope, authorize):
        self.journal, self.scope, self.authorize = journal, scope, authorize

    def current(self):
        if self.authorize() is not True:
            raise PermissionError('声音档案范围已变化')
        return True

    def get(self):
        self.current()
        row = self.journal.fetch(NS, 'profile', self.scope)
        result = dict(profile=deepcopy(DEFAULT) if row is None else validate(row['data']),
                      revision=0 if row is None else row['revision'],
                      updated_at=None if row is None else row['updated_at'],
                      persisted=row is not None, audio_stored_on_server=False,
                      capabilities=dict(tts='android_system', asr='system_recognizer',
                          cloned_voice=False, expressive_instructions=False))
        self.current()
        return result

    def save(self, profile, expected_revision):
        profile = validate(profile)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('声音档案版本无效')
        self.current()
        self.journal.put(NS, 'profile', self.scope, profile,
                         expected_revision=expected_revision, authorize=self.current)
        return self.get()

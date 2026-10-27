"""PC business output uses the existing durable TLS sender and final gate."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
import time
from urllib.parse import unquote

from .models import canonical, private_scope
from .delivery_types import make_task

NAMESPACE = 'tls.native.pc.business.delivery.v1'


class NativeBusinessDelivery:
    def __init__(self, integrations):
        self.integrations = integrations
        self._lock = asyncio.Lock()

    def _resources(self, scope):
        scope = private_scope(scope)
        host = self.integrations._host()
        owner = self.integrations.pc_full
        if (self.integrations._closed or owner is None or not owner.active
                or not owner.legacy_closed() or host is None or host._closed
                or not host.authorized_scope(scope)):
            raise PermissionError('current native PC owner and scope required')
        services = host.runtime.native_services
        if services.delivery is None or not services._delivery_allowed(scope):
            raise PermissionError('existing delivery lane not authorized')
        return host, owner, services.delivery

    async def _image(self, host, raw):
        raw = str(raw or '')
        if raw.startswith('file://'):
            raw = unquote(raw[7:])
        media = Path(host.runtime.native_services.path)/'media'
        media.mkdir(parents=True,exist_ok=True)
        if raw.startswith('base64://'):
            encoded = raw[9:]
            if len(encoded) > 28*1024**2:
                raise ValueError('image exceeds existing sender limit')
            data = base64.b64decode(encoded,validate=True)
        elif raw.startswith(('https://','http://')):
            service = getattr(host.runtime,'image_service',None)
            transport = getattr(service,'_transport',None)
            if transport is None:
                raise ValueError('configured image transport required for remote business image')
            reply = await transport.download(raw,timeout=20,max_bytes=20*1024**2)
            if getattr(reply,'status',None) != 200:
                raise ValueError('business image download failed')
            data = reply.body
        else:
            path = Path(raw).resolve()
            roots = (media.resolve(),(self.integrations.data_dir.parent/'astrbot_plugin_private_companion').resolve())
            if (not any(path.is_relative_to(root) for root in roots) or not path.is_file()
                    or path.is_symlink() or path.stat().st_size > 20*1024**2):
                raise ValueError('business image must belong to the existing media roots')
            data = await asyncio.to_thread(path.read_bytes)
        if not data or len(data) > 20*1024**2:
            raise ValueError('bounded image required')
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(data)) as image:
            image.verify()
        digest = hashlib.sha256(data).hexdigest()
        destination = media/('pc-'+digest+'.image')
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                raise ValueError('owned media digest changed')
        else:
            with destination.open('xb') as stream:stream.write(data)
        return str(destination)

    async def _audio(self, host, raw):
        raw=str(raw or '')
        if raw.startswith('file://'):raw=unquote(raw[7:])
        path=Path(raw).resolve()
        media=Path(host.runtime.native_services.path)/'media'
        roots=(media.resolve(),(self.integrations.data_dir.parent/'astrbot_plugin_private_companion').resolve())
        if (not any(path.is_relative_to(root) for root in roots) or path.is_symlink()
                or not path.is_file() or not 0 < path.stat().st_size <= 20*1024**2):
            raise ValueError('business audio must belong to the existing media roots')
        data=await asyncio.to_thread(path.read_bytes)
        digest=hashlib.sha256(data).hexdigest()
        media.mkdir(parents=True,exist_ok=True)
        suffix=path.suffix.lower()
        if suffix not in {'.wav','.mp3','.ogg','.flac','.m4a','.aac','.amr','.silk','.pcm'}:
            raise ValueError('business audio format is unsupported')
        destination=media/('pc-'+digest+suffix)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                raise ValueError('owned audio digest changed')
        else:
            with destination.open('xb') as stream:stream.write(data)
        return str(destination)

    async def platform_action(self, scope, action, payload):
        """One scoped private poke, recorded before the existing SDK action."""
        scope=private_scope(scope)
        async with self._lock:
            host,owner,_=self._resources(scope)
            if (action!='poke' or payload.get('group_id') or str(payload.get('user_id',''))!=scope['user_id']
                    or not scope['user_id'].isdigit() or not owner._authorize('platform_action',scope)):
                raise PermissionError('actual private native PC poke scope required')
            source=getattr(owner.service,'_tls_source',None)
            if not isinstance(source,dict) or not source.get('event_id'):
                raise PermissionError('genuine bound input occurrence required')
            occurrence=payload.get('source_event_id')
            if not isinstance(occurrence,str) or not occurrence.startswith('pc.poke.') or len(occurrence)!=72:
                raise PermissionError('bounded sourced platform occurrence required')
            key='action:'+hashlib.sha256(canonical([scope,action,occurrence]).encode()).hexdigest()
            prior=host.journal.fetch(NAMESPACE,key,scope)
            if prior:return dict(state=prior['data']['state'],id=key,replayed=False)
            platform_id=scope['session_id'].split(':',1)[0]
            platforms=[item for item in self.integrations.context.platform_manager.get_insts()
                if str(getattr(item.meta(),'id',''))==platform_id]
            if len(platforms)!=1 or 'aiocqhttp' not in type(platforms[0]).__module__:
                raise PermissionError('the exact private QQ platform is unavailable')
            client=platforms[0].get_client()
            if not callable(getattr(client,'friend_poke',None)):
                raise RuntimeError('the current platform does not implement private poke')
            record=dict(state='unknown',action=action,source_event_id=source['event_id'],created_at=host.clock())
            saved=host.journal.put(NAMESPACE,key,scope,record,expected_revision=0,
                authorize=lambda:owner._authorize('platform_action',scope))
            # A transport interruption leaves UNKNOWN. It is never reissued by
            # another task, hotload or a second click for the same occurrence.
            result=await client.friend_poke(user_id=int(scope['user_id']))
            if isinstance(result,dict) and (result.get('status')=='failed' or result.get('retcode',0)!=0):
                state='failed'
            else:state='confirmed'
            host.journal.put(NAMESPACE,key,scope,dict(record,state=state,completed_at=host.clock()),
                expected_revision=saved['revision'])
            return dict(state=state,id=key)

    async def dispatch(self, scope, umo, chain, metadata):
        scope = private_scope(scope)
        if scope['session_id'] != umo:
            raise PermissionError('actual session does not match business scope')
        async with self._lock:
            host, owner, delivery = self._resources(scope)
            journal = host.journal
            text, images, audios = [], [], []
            for component in chain:
                kind = type(component).__name__
                if kind in {'Plain','TextPart'} and isinstance(getattr(component,'text',None),str):
                    text.append(component.text)
                elif kind == 'Image':
                    value = getattr(component,'file',None) or getattr(component,'url',None)
                    images.append(await self._image(host,value))
                elif kind == 'Record':
                    value=getattr(component,'file',None) or getattr(component,'url',None)
                    audios.append(await self._audio(host,value))
                else:
                    raise ValueError('unsupported business output component: '+kind)
            if len(images)>1 or len(audios)>1 or (not ''.join(text).strip() and not audios):
                raise ValueError('the existing companion lane needs text or one audio, and at most one image')
            text = ''.join(text)
            audio=audios[0] if audios else None
            audio_text=bool(text.strip())
            if not text.strip():text='角色语音'
            if len(text)>4000:
                raise ValueError('business output exceeds the existing sender text contract')
            occurrence = metadata.get('source_event_id')
            if not isinstance(occurrence,str) or not occurrence:
                raise ValueError('stable sourced business occurrence required')
            event = 'pc.business:'+hashlib.sha256(canonical([scope,occurrence]).encode()).hexdigest()
            identity = make_task(scope,event,text=text,images=images,audio=audio,audio_text=audio_text,now=host.clock())['id']
            lane = journal.fetch(NAMESPACE,'lane',scope)
            if lane is not None:
                previous = delivery.store.get(lane['data']['task_id'])
                if ((previous is None or previous.get('state') not in {'confirmed','failed','cancelled','expired','rejected'})
                        and lane['data'].get('admission_denied') is not True):
                    return dict(state=previous.get('state','unknown') if previous else 'unknown',
                        task_id=lane['data']['task_id'],submitted=False)
            existing = journal.fetch(NAMESPACE,'task:'+identity,scope)
            if existing is None:
                data = dict(task_id=identity,event_id=event,source='tls.native.pc.business',
                    occurrence_sha256=hashlib.sha256(occurrence.encode()).hexdigest(),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),images=images,
                    audio=audio,audio_text=audio_text,
                    created_at=host.clock())
                journal.put(NAMESPACE,'task:'+identity,scope,data,expected_revision=0)
                journal.put(NAMESPACE,'lane',scope,data,expected_revision=lane['revision'] if lane else 0)
            task = await delivery.submit(scope,event,text=text,images=images,trigger='timer',max_attempts=1,
                audio=audio,audio_text=audio_text)
            if task.get('state')=='candidate':
                lane=journal.fetch(NAMESPACE,'lane',scope)
                if lane and lane['data'].get('task_id')==identity:
                    journal.put(NAMESPACE,'lane',scope,dict(lane['data'],admission_denied=True),expected_revision=lane['revision'])
                return dict(state='rejected',task_id=identity,submitted=False)
            deadline = time.monotonic()+20
            while task.get('state') in {'approved','queued','claimed','sending','retry_wait'} and time.monotonic()<deadline:
                await asyncio.sleep(.25)
                self._resources(scope)
                task = await asyncio.to_thread(delivery.store.get,identity)
                if task is None: return dict(state='unknown',task_id=identity)
            return dict(state=task.get('state','unknown'),task_id=identity,
                confirmed=task.get('state')=='confirmed',submitted=True)

    async def owns_task(self, scope, task):
        try:
            host, owner, delivery = self._resources(scope)
            record = await asyncio.to_thread(host.journal.fetch,NAMESPACE,'task:'+task['id'],scope)
            return bool(record and record['data'].get('task_id')==task['id'])
        except Exception:return False

    async def delivery_allowed(self, scope, task):
        if not await self.owns_task(scope,task):return False
        host, owner, delivery = self._resources(scope)
        record = await asyncio.to_thread(host.journal.fetch,NAMESPACE,'task:'+task['id'],scope)
        return bool(record and record['data']['text_sha256']==hashlib.sha256(task['text'].encode()).hexdigest()
            and record['data']['images']==task['images']
            and record['data'].get('audio')==task.get('audio')
            and (not task.get('audio') or record['data'].get('audio_text')==task.get('audio_text')))

"""One borrowed view of the native Phone service's existing PPB client.

App-entry consumers and the Presence provider share the same original request
lock/cache. This adapter owns no transport, polling loop or legacy instance.
"""
from __future__ import annotations

import asyncio
import math
import time

from .models import EvidenceKind, Observation, plain, private_scope
from .native_phone_connector import _section

_SECTIONS={'device.battery':'battery','device.screen':'screen','device.network':'network',
           'device.app':'app','device.audio':'audio','device.device':'device',
           'user_activity':'activity'}


class NativePhoneSharedConnector:
    def __init__(self,service,*,authorize,clock=time.time):
        from .native_phone_service.runtime import NativePhoneService
        if not isinstance(service,NativePhoneService) or not callable(authorize) or not callable(clock):
            raise ValueError('native Phone service and existing scope authorizer required')
        self.service,self.authorize,self.clock=service,authorize,clock
        self._closed=False
        self._reads=0;self._returned=0;self._failures=0

    def _allowed(self,scope):
        owner=getattr(getattr(self.service,'config',None),'plugin',None)
        return (not self._closed and self.service._active and not self.service._music_stopping
                and (owner is None or getattr(owner,'_native_phone_service',None) is self.service
                     and getattr(owner,'context',None) is self.service.context)
                and self.authorize(scope) is True)

    async def read(self,scope):
        self._reads+=1
        scope=private_scope(scope)
        if not self._allowed(scope):return []
        service=self.service;adapter=service._presence_adapter
        eligible=getattr(adapter,'_eligible',None)
        current=lambda:(self.service is service and service._presence_adapter is adapter and self._allowed(scope)
                        and (not callable(eligible) or eligible(scope)))
        now=self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or now<0:
            raise ValueError('valid observation clock required')
        try:
            collectors=[adapter.collect_device(scope,float(now))]
            music=getattr(adapter,'collect_music',None)
            if callable(music):collectors.append(music(scope,float(now)))
            batches=await asyncio.gather(*collectors,return_exceptions=True)
            for batch in batches:
                if isinstance(batch,asyncio.CancelledError):raise batch
            records=batches[0]
            if isinstance(records,BaseException):raise records
        except Exception:
            self._failures+=1
            raise
        if not current():return []
        music_records=batches[1] if len(batches)>1 else []
        if isinstance(music_records,BaseException):
            self._failures+=1;music_records=[]
        if music_records and callable(eligible) and not eligible(scope,music=True):
            music_records=[]
        received=self.clock();result=[]
        if type(received) not in (int,float) or not math.isfinite(received) or received<0:
            raise ValueError('valid receipt clock required')
        for record in records[:64]:
            domain=record.get('domain');section=_SECTIONS.get(domain)
            if section is None:continue
            status=record.get('status','unknown')
            observed=record.get('observed_at');ttl=record.get('ttl_seconds')
            numeric=(type(observed) in (int,float) and math.isfinite(observed)
                     and type(ttl) in (int,float) and math.isfinite(ttl) and ttl>=0)
            expires=observed+ttl if numeric else None
            payload=_section(section,record.get('value')) if status=='fresh' else None
            if payload is None and status=='fresh':status='unknown'
            provenance={'connector':'native_phone_shared_client','section':section,
                        'timestamp_basis':'existing_presence_collector_observation'}
            shared={'phone_source':'confirmed_link','source_scope_shared':True}
            if record.get('provenance')==shared:
                provenance.update(shared)
            result.append(Observation(source_id='phone.device',observation_type=domain,
                scope=scope,observed_at=observed if numeric else None,received_at=received,
                expires_at=expires,payload=payload,
                provenance=provenance,
                permission_scope='phone.read',evidence_kind=EvidenceKind.REAL_OBSERVATION,
                status=status,device_id=record.get('device_id'),
                importance=record.get('importance','normal'),change_key=record.get('change_key')))
        for record in music_records[:1] if isinstance(music_records,list) and len(result)<64 else []:
            try:
                if not isinstance(record,dict) or record.get('domain')!='music':continue
                payload=record.get('value')
                if not isinstance(payload,dict):continue
                payload=plain(payload,32768)
                observed=record.get('observed_at');ttl=record.get('ttl_seconds')
                numeric=(type(observed) in (int,float) and math.isfinite(observed)
                         and type(ttl) in (int,float) and math.isfinite(ttl) and ttl>=0)
                provenance={'connector':'native_phone_shared_client','section':'music',
                            'timestamp_basis':'existing_presence_collector_observation'}
                shared={'phone_source':'confirmed_link','source_scope_shared':True}
                if record.get('provenance')==shared:provenance.update(shared)
                result.append(Observation(source_id='phone.music',observation_type='music',
                    scope=scope,observed_at=observed if numeric else None,received_at=received,
                    expires_at=observed+ttl if numeric else None,payload=payload,provenance=provenance,
                    permission_scope='phone.read',evidence_kind=EvidenceKind.REAL_OBSERVATION,
                    status=record.get('status','unknown'),device_id=record.get('device_id'),
                    importance=record.get('importance','normal'),change_key=record.get('change_key')))
            except (ValueError,TypeError):
                self._failures+=1
        if not current():return []
        self._returned+=len(result)
        return result

    def diagnostics(self):
        cache=getattr(self.service.client,'_cache',None)
        return {'active':not self._closed and self.service._active,'shared_transport':True,
                'reads':self._reads,'returned':self._returned,'failures':self._failures,
                'requests':None,'cache_hits':None,
                'transport_metrics':'not_counted_by_borrowed_view',
                'cache_entries':len(cache) if isinstance(cache,dict) else None,
                'transport_sessions_owned':0,'polling_tasks':0,'llm_calls':0,
                'model_calls':0,'sends':0,'writes':0}

    async def close(self):
        # The service remains the sole client owner; stopping an App-entry
        # consumer must not close PPB access for care or ordinary chat.
        self._closed=True

    aclose=close

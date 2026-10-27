"""Owner-managed grants, revocation, idempotent resource reservations and stop.

No model tool exposes grant(). The host owner must configure permissions.
Budgets are an additional ceiling; existing chat/send budgets remain decisive.
"""
from __future__ import annotations
import hashlib
import math
import time
from datetime import datetime, timezone

from .journal import JournalConflict
from .models import canonical, private_scope

CAPABILITIES = frozenset({"observe.persist", "time.read", "clock.read", "presence.read", "music.catalog.read", "weather.read", "music.read",
    "catalog.read", "device.read", "memory.write", "memory.read", "memory.correct",
    "context.read", "context.feature.read", "context.private.read", "narrative.read", "narrative.write", "preferences.write",
    "memory.delete", "share.propose", "share.send", "explore.local", "action.simulate"})
DEFAULT_LIMITS = {"observations": 2000, "explorations": 10, "shares": 8,
                  "llm_calls": 0, "external_calls": 0, "simulated_actions": 8}
_CAPABILITY_ALIASES = {'clock.read':'time.read','music.catalog.read':'catalog.read'}


class Governance:
    def __init__(self, journal, *, clock=time.time, limits=None):
        self.journal, self.clock = journal, clock
        self.limits = dict(DEFAULT_LIMITS)
        for name, value in (limits or {}).items():
            if name not in self.limits or isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100000:
                raise ValueError("invalid resource limit")
            self.limits[name] = value

    @staticmethod
    def _key(capability, source_id):
        if capability not in CAPABILITIES:
            raise ValueError("unsupported capability")
        if source_id is not None and (not isinstance(source_id, str) or not source_id or len(source_id) > 128):
            raise ValueError("invalid permission source")
        return hashlib.sha256(canonical([_CAPABILITY_ALIASES.get(capability,capability),source_id]).encode()).hexdigest()

    def grant(self, capability, scope, *, source_id=None, expires_at, granted_by, purpose):
        scope=private_scope(scope);key=self._key(capability,source_id)
        if (isinstance(expires_at,bool) or not isinstance(expires_at,(int,float)) or
                not math.isfinite(expires_at) or expires_at<=self.clock()):
            raise ValueError("grant needs a future finite expiry")
        if not isinstance(granted_by,str) or not granted_by.strip() or not isinstance(purpose,str) or not purpose.strip():
            raise ValueError("grant owner and purpose are required")
        data={"capability":capability,"source_id":source_id,"expires_at":expires_at,
              "granted_by":granted_by[:160],"purpose":purpose[:240],"active":True,"granted_at":self.clock()}
        result=self.journal.put('grants',key,scope,data)
        self.journal.audit('PermissionGranted',scope,key,'active',{'capability':capability})
        return result

    def allows(self, capability, scope, source_id=None):
        scope=private_scope(scope)
        paused=self.journal.fetch('control','paused',scope)
        if paused and paused['data'].get('paused'):return False
        grant=self.journal.fetch('grants',self._key(capability,source_id),scope)
        return bool(grant and grant['data'].get('active') is True and grant['data'].get('expires_at',0)>self.clock())

    def revoke(self, capability, scope, *, source_id=None):
        key=self._key(capability,source_id)
        for _ in range(8):
            row=self.journal.fetch('grants',key,scope)
            if not row:return False
            data=dict(row['data'],active=False,revoked_at=self.clock())
            try:self.journal.put('grants',key,scope,data,expected_revision=row['revision']);break
            except JournalConflict:continue
        else:raise JournalConflict('permission revoke conflict')
        self.journal.audit('PermissionRevoked',scope,key,'revoked',{'capability':capability})
        return True

    def pause(self, scope, *, paused=True):
        if not isinstance(paused,bool):raise ValueError('paused must be boolean')
        self.journal.put('control','paused',scope,{'paused':paused,'updated_at':self.clock()})
        self.journal.audit('SystemPaused' if paused else 'SystemResumed',scope,'control','paused' if paused else 'active')

    def reserve(self, resource, units, scope, *, reservation_id):
        if resource not in self.limits or isinstance(units,bool) or not isinstance(units,int) or units<0:
            raise ValueError('invalid resource reservation')
        if not isinstance(reservation_id,str) or not reservation_id or len(reservation_id)>256:
            raise ValueError('invalid reservation identity')
        day=datetime.fromtimestamp(self.clock(),timezone.utc).date().isoformat()
        return self.journal.reserve_resource(scope,day,resource,reservation_id,units,self.limits[resource])

    def budget(self, resource, scope):
        if resource not in self.limits:raise ValueError('unknown resource')
        day=datetime.fromtimestamp(self.clock(),timezone.utc).date().isoformat()
        return {'used':self.journal.resource_usage(scope,day,resource),'limit':self.limits[resource], 'day_utc':day}

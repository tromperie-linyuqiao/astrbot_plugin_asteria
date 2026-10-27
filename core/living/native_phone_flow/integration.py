"""Public native pacing entry for explicitly connected producer plugins.

No old Phone/DialogueFlow discovery and no fallback after an attempted send.
Existing callers must explicitly adopt this TLS entry during their handoff.
"""
import hashlib
import sys
import types
from pathlib import Path

from .runtime import NativePhoneFlow

_LEGACY_MODULES=(
    'data.plugins.astrbot_plugin_phone_perception.flow.integration',
    'astrbot_plugin_phone_perception.flow.integration',
    'data.plugins.astrbot_plugin_dialogue_flow.integration',
    'astrbot_plugin_dialogue_flow.integration',
)
_PC_MODULES=('data.plugins.astrbot_plugin_private_companion.main',
             'astrbot_plugin_private_companion.main')
_LEGACY_SHA='cb54d94d611a90eb13cecb25b0f8d4234b5ef7918fef8118ce0455d4a36324d3'
_STATE_KEY='_tls_native_phone_flow_forwarders'
_STATE_VERSION='tls.native.phone_flow.forwarders.v1'


def _legacy_function(value):
    if (type(value) is not types.FunctionType or value.__module__ not in _LEGACY_MODULES
            or value.__name__!='send_with_flow' or value.__closure__ is not None
            or value.__defaults__ is not None or value.__kwdefaults__ is not None
            or value.__globals__.get('__name__')!=value.__module__
            or value.__globals__.get('PLUGIN_NAMES')!=
                ('astrbot_plugin_phone_perception','astrbot_plugin_dialogue_flow')):
        return False
    filename=value.__code__.co_filename
    suffix=filename.replace('\\','/')
    if not (suffix.endswith('/astrbot_plugin_phone_perception/flow/integration.py')
            or suffix.endswith('/astrbot_plugin_dialogue_flow/integration.py')):
        return False
    path=Path(filename)
    if not path.is_file() or path.stat().st_size>8192:return False
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=_LEGACY_SHA:return False
    module=compile(raw,filename,'exec',dont_inherit=True)
    expected=next((item for item in module.co_consts if isinstance(item,types.CodeType)
                   and item.co_name=='send_with_flow'),None)
    return expected is not None and value.__code__==expected


def _old_owner_active(context):
    getter=getattr(context,'get_registered_star',None)
    if not callable(getter):return False
    return any(getattr(getter(name),'activated',False) is True for name in
               ('astrbot_plugin_phone_perception','astrbot_plugin_dialogue_flow'))


def _native_ready(context,service):
    from ..native_phone_service.runtime import NativePhoneService
    if (not isinstance(service,NativePhoneService) or service.context is not context
            or service._active is not True or service._music_stopping
            or not isinstance(service.dialogue_flow,NativePhoneFlow)
            or service.dialogue_flow._active is not True):
        return False
    getter=getattr(context,'get_registered_star',None)
    metadata=getter('astrbot_plugin_virtual_body') if callable(getter) else None
    plugin=getattr(metadata,'star_cls',None) if getattr(metadata,'activated',False) is True else None
    return getattr(plugin,'_native_phone_service',None) is service


class LegacyFlowForwarders:
    """Fixed-module CAS only. A stopped native owner leaves a refusing fence.

    The retained state is RAM data in the same SDK Context. A normal TLS reload
    can adopt it after verifying the exact original functions and slot identities;
    no old helper is restored merely because TLS stopped.
    """
    def __init__(self,state):self._state=state

    @property
    def forwarder(self):return self._state['wrapper']

    def status(self):
        state=self._state
        return {'state':'native' if state['enabled'] else 'fenced',
                'bound_slots':len(state['slots']),'pc_aliases':state['pc_aliases'],
                'not_present':list(state['not_present']),'errors':state['errors'],
                'global_caller_coverage_proven':False}

    def restore_exact(self,*,allow_legacy_restore=False):
        state=self._state;context=state['context'];state['enabled']=False
        if any(vars(module).get(name) is not state['wrapper'] for module,name,_ in state['slots']):
            return {'state':'restore_pending','reason':'slot_changed','restored':0}
        if getattr(state['service'],'_active',False) is True:
            return {'state':'fenced','reason':'native_owner_active','restored':0}
        if allow_legacy_restore is not True or not _old_owner_active(context):
            return {'state':'fenced','reason':'legacy_restore_not_authorized','restored':0}
        if any(not _legacy_function(original) for _,_,original in state['slots']):
            return {'state':'restore_pending','reason':'legacy_source_changed','restored':0}
        for module,name,original in state['slots']:
            # All slots were compared before any mutation; never overwrite an
            # intervening foreign writer when restoring an explicit old owner.
            if vars(module).get(name) is not state['wrapper']:
                return {'state':'restore_pending','reason':'slot_changed','restored':0}
        for module,name,original in state['slots']:setattr(module,name,original)
        if getattr(context,_STATE_KEY,None) is state:delattr(context,_STATE_KEY)
        return {'state':'restored','restored':len(state['slots'])}


def install_legacy_forwarders(context,native_service):
    """Forward only reviewed, already-loaded helper/alias slots to TLS.

    Exact four helper module names and two existing PC.main namespaces are the
    entire inventory. No module is imported and sys.modules is never scanned.
    Missing modules remain explicitly not_present, not a claim of global coverage.
    """
    if not _native_ready(context,native_service) or _old_owner_active(context):
        raise RuntimeError('one active native phone owner and stopped old owners required')
    state=getattr(context,_STATE_KEY,None)
    if state is not None:
        required={'version','context','service','slots','wrapper','token','enabled','sender',
                  'pc_aliases','not_present','errors','ready'}
        if (type(state) is not dict or set(state)!=required or state['version']!=_STATE_VERSION
                or state['context'] is not context or not isinstance(state['slots'],list)
                or len(state['slots'])>256 or type(state['wrapper']) is not types.FunctionType
                or getattr(state['wrapper'],'_tls_phone_flow_token',None) is not state['token']
                or any(type(module) is not types.ModuleType or not _legacy_function(original)
                       or vars(module).get(name) is not state['wrapper']
                       for module,name,original in state['slots'])):
            raise RuntimeError('retained native flow fence changed')
        # No restoration window: the same refusing wrapper adopts the current
        # service and current TLS sender only after all exact-slot checks pass.
        state['service']=native_service;state['sender']=send_with_flow;state['ready']=_native_ready;state['enabled']=True
        return LegacyFlowForwarders(state)
    slots=[];originals=[];missing=[];pc_aliases=0
    for module_name in _LEGACY_MODULES:
        module=sys.modules.get(module_name)
        if module is None:missing.append(module_name);continue
        if type(module) is not types.ModuleType:raise RuntimeError('legacy helper module changed')
        original=vars(module).get('send_with_flow')
        if not _legacy_function(original):raise RuntimeError('legacy flow helper changed')
        slots.append((module,'send_with_flow',original));originals.append(original)
    for module_name in _PC_MODULES:
        module=sys.modules.get(module_name)
        if module is None:continue
        if type(module) is not types.ModuleType or len(vars(module))>4096:
            raise RuntimeError('PC module inventory unavailable')
        for name,value in list(vars(module).items()):
            if any(value is original for original in originals):
                slots.append((module,name,value));pc_aliases+=1
    if len(slots)>256:raise RuntimeError('flow alias inventory capacity')
    state={'version':_STATE_VERSION,'context':context,'service':native_service,'slots':slots,
           'wrapper':None,'token':object(),'enabled':True,'sender':send_with_flow,
           'pc_aliases':pc_aliases,'not_present':missing,'errors':0,'ready':_native_ready}
    async def forward(call_context,umo,event_key,chain):
        if (call_context is not state['context'] or not state['enabled']
                or not state['ready'](call_context,state['service'])):
            return {'sent':False,'reason':'unavailable'}
        try:return await state['sender'](call_context,umo,event_key,chain)
        except Exception:
            # Do not expose exception details or invite a fallback old sender.
            state['errors']=min(1000000,state['errors']+1)
            return {'sent':False,'reason':'delivery_uncertain'}
    forward._tls_phone_flow_token=state['token'];state['wrapper']=forward
    if any(vars(module).get(name) is not original for module,name,original in slots):
        raise RuntimeError('legacy flow slot changed before install')
    for module,name,_ in slots:setattr(module,name,forward)
    if slots:setattr(context,_STATE_KEY,state)
    return LegacyFlowForwarders(state)


async def send_with_flow(context, umo, event_key, chain):
    getter=getattr(context,'get_registered_star',None)
    metadata=getter('astrbot_plugin_virtual_body') if callable(getter) else None
    plugin=getattr(metadata,'star_cls',None) if getattr(metadata,'activated',False) is True else None
    phone=getattr(plugin,'_native_phone_service',None)
    flow=getattr(phone,'dialogue_flow',None)
    if (getattr(phone,'_active',False) is not True or not isinstance(flow,NativePhoneFlow)
            or flow._active is not True):
        return {'sent':False,'reason':'unavailable'}
    return await flow.send_proactive(umo,event_key,chain)

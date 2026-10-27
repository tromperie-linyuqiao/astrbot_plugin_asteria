"""Keep existing TLS core records usable after the complete MC owner retires.

The stored handoff is retained. A successor proves the old source/config/data
identity and its own real TLS lifecycle; it never fabricates a legacy Star or
rewrites a user's memory to manufacture a new ownership history.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

from .models import canonical
from . import native_core_handoff as previous

_SEAL = object()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeMCCoreBinding:
    def __init__(self, runtime, *, _seal=None):
        if _seal is not _SEAL:
            raise PermissionError('native runtime binding required')
        self.runtime, self._seal = runtime, _seal

    def current(self):
        try:
            from .native_mc_owned_runtime import NativeOwnedMCContextRuntime
            rt = self.runtime
            owner = getattr(rt.plugin, '_native_server_integrations', None)
            return (self._seal is _SEAL and type(rt) is NativeOwnedMCContextRuntime
                and rt._live() and owner is not None and owner.mc is rt
                and owner.mc_full is rt.companion and rt.companion.active
                and rt.companion.legacy_quiesced() is True
                and rt.service.config.bool('memory_tools.enable_core_memory_tool', True) is False)
        except Exception:
            return False

    @property
    def proof(self):
        if not self.current():
            raise PermissionError('native memory successor not current')
        rt = self.runtime
        path = Path(rt.store.db_path).resolve(); st = path.stat()
        package = type(rt.service).__module__.rsplit('.', 1)[0]
        paths = {'main':Path(sys.modules[type(rt.companion).__module__].__file__)}
        paths.update({key:Path(sys.modules[package+'.'+key].__file__) for key in ('service','config','store')})
        raw = rt.service.config.raw
        digest = previous._config_digest(raw)
        return dict(owner_kind='tls_full_memory_companion', config_sha256=digest,
            persisted_config_sha256=digest,
            service_token=_sha(str(id(rt.service)).encode()),
            config_token=_sha(str(id(rt.service.config)).encode()),
            store_token=_sha(str(id(rt.store)).encode()),
            connection_token=_sha(str(id(rt.store._conn)).encode()),
            database_identity_sha256=previous._json_digest(dict(path=str(path),device=st.st_dev,inode=st.st_ino)),
            source_sha256={key:_sha(filename.read_bytes()) for key,filename in paths.items()})

    def predecessor_matches(self, saved):
        """Only an already-native persisted owner can use this successor."""
        if not self.current() or not isinstance(saved, dict):
            return False
        try:
            rt = self.runtime
            root = Path(sys.modules[type(rt.plugin).__module__].__file__).resolve().parent.parent
            legacy = root/'astrbot_plugin_memory_companion'
            files = {'main':legacy/'main.py', **{k:legacy/'core'/(k+'.py') for k in ('service','config','store')}}
            actual = {key:_sha(path.read_bytes()) for key,path in files.items()}
            raw = json.loads((root.parent/'config/astrbot_plugin_memory_companion_config.json').read_bytes())
            return (actual == previous._SOURCE_HASHES == saved.get('source_sha256')
                and previous._config_digest(raw) == saved.get('config_sha256') == saved.get('persisted_config_sha256')
                and self.proof['database_identity_sha256'] == saved.get('database_identity_sha256')
                and saved.get('legacy_inventory',{}).get('core_rows') == 0)
        except Exception:
            return False


def capture_owned_core(context):
    try:
        rows = [row for row in context.get_all_stars()
            if getattr(row,'root_dir_name',None)=='astrbot_plugin_virtual_body'
            and getattr(row,'activated',False) is True]
        if len(rows) != 1:
            return None
        plugin = rows[0].star_cls
        rt = getattr(plugin,'_native_mc_takeover',None)
        gate = NativeMCCoreBinding(rt,_seal=_SEAL)
        return gate if gate.current() else None
    except Exception:
        return None

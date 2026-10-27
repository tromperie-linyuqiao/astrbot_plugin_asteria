"""A nested config view that never clears or rolls back unrelated settings."""
from __future__ import annotations

import copy
from collections.abc import MutableMapping
from contextlib import nullcontext


class ConfigSection(MutableMapping):
    def __init__(self, parent, key: str = "living_phone_flow", *, write_lock=None):
        self.parent = parent
        self.key = key
        self.write_lock = write_lock
        if key not in parent:
            parent[key] = {}
        self._section()

    def _section(self):
        section = self.parent[self.key]
        if not isinstance(section, MutableMapping):
            raise ValueError("聊天节奏配置必须是对象")
        return section

    def __getitem__(self, key):
        return self._section()[key]

    def __setitem__(self, key, value):
        self._section()[key] = value

    def __delitem__(self, key):
        del self._section()[key]

    def __iter__(self):
        return iter(self._section())

    def __len__(self):
        return len(self._section())

    def snapshot(self):
        return copy.deepcopy(dict(self._section()))

    def restore(self, snapshot):
        # Replace this namespace only. Other services share the parent config.
        self.parent[self.key] = copy.deepcopy(snapshot)

    def save_config(self):
        # The async API lock cannot serialize synchronous phone command saves.
        with self.write_lock if self.write_lock is not None else nullcontext():
            return self.parent.save_config()

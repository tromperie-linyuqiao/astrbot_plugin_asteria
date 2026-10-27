# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import shutil
from pathlib import Path


def cleanup_storage_bytecode_cache() -> None:
    """Remove Python bytecode generated inside this small storage helper package."""
    pycache = Path(__file__).resolve().parent / "__pycache__"
    if pycache.exists() and pycache.is_dir():
        shutil.rmtree(pycache, ignore_errors=True)


# Native lifecycle never deletes bytecode caches during shutdown.

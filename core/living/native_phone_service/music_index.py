"""Reuse the already-shipped TLS exact local catalog implementation."""
from ..native_music_catalog import (NativeMusicCatalog as MusicIndex,
    display_text, match_music, normalize_text)

__all__ = ["MusicIndex", "display_text", "match_music", "normalize_text"]

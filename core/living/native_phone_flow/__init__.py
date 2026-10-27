"""TLS-owned phone conversational pacing; PPB collection is external.

No old Phone plugin instance is imported or needed. The host must transfer
the old hooks and drain their pending work before activating this runtime.
"""
from .config import ConfigSection
from .runtime import NativePhoneFlow

__all__ = ["ConfigSection", "NativePhoneFlow"]

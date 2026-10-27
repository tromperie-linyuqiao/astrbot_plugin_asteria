"""Explicit QQ sticker wire component; construction only, never sends.

AstrBot 4.26.6 special-cases Image/Record and discards their extra fields.
Use the base-component serialization path while retaining the image wire type.
NapCat protocol: https://napneko.github.io/develop/msg#image
Actual installed NapCat compatibility and QQ appearance require separate tests.
"""
import base64
from astrbot.api.event import MessageChain
from astrbot.api.message_components import BaseMessageComponent, ComponentType

MAX_STICKER_BYTES = 8 * 1024 * 1024


class QQStickerComponent(BaseMessageComponent):
    """Not an Image subclass: SDK must preserve the explicit sticker fields."""
    type: ComponentType = ComponentType.Image
    file: str

    def __init__(self, raw: bytes):
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_STICKER_BYTES:
            raise ValueError('nonempty bounded original sticker bytes required')
        super().__init__(type=ComponentType.Image,
            file='base64://' + base64.b64encode(raw).decode('ascii'))

    def toDict(self):
        return {'type': 'image', 'data': {
            'file': self.file, 'sub_type': 1, 'summary': '[动画表情]'}}


def build_qq_sticker_chain(raw: bytes) -> MessageChain:
    """One unchanged byte payload, one component, no plain text or transport."""
    return MessageChain([QQStickerComponent(raw)], use_t2i_=False, use_markdown_=False)

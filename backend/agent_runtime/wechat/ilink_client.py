"""iLink Bot API HTTP client.

Implements Tencent's iLink protocol for WeChat bot connectivity:
  - QR code login (get_bot_qrcode → poll qrcode_status)
  - Long-poll message receiving (getupdates)
  - Message sending (sendmessage, text + media)
  - Typing indicators (sendtyping)
  - CDN media upload (getuploadurl → upload)

All calls are plain HTTP POST/GET to {baseurl}/ilink/bot/*.
Authentication: Bearer <bot_token> + X-WECHAT-UIN header.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
QRCODE_URL = f"{DEFAULT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
QRCODE_STATUS_URL = f"{DEFAULT_BASE_URL}/ilink/bot/get_qrcode_status?qrcode="

LONGPOLL_TIMEOUT = 35  # seconds — iLink default
SEND_TIMEOUT = 15
CONFIG_TIMEOUT = 10
LOGIN_POLL_INTERVAL = 2  # seconds

# Message types
MSG_TYPE_NONE = 0
MSG_TYPE_USER = 1
MSG_TYPE_BOT = 2

# Message states
MSG_STATE_NEW = 0
MSG_STATE_GENERATING = 1
MSG_STATE_FINISH = 2

# Item types
ITEM_TYPE_NONE = 0
ITEM_TYPE_TEXT = 1
ITEM_TYPE_IMAGE = 2
ITEM_TYPE_VOICE = 3
ITEM_TYPE_FILE = 4
ITEM_TYPE_VIDEO = 5

# CDN media types
CDN_MEDIA_IMAGE = 1
CDN_MEDIA_VIDEO = 2
CDN_MEDIA_FILE = 3

# Typing
TYPING_START = 1
TYPING_CANCEL = 2

# Error codes
ERR_SESSION_EXPIRED = -14


# ═══════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class QRCodeResponse:
    qrcode: str
    qrcode_img_content: str  # base64-encoded image


@dataclass
class Credentials:
    bot_token: str
    ilink_bot_id: str
    base_url: str
    ilink_user_id: str

@dataclass
class TextItem:
    text: str


@dataclass
class MediaInfo:
    encrypt_query_param: str = ""
    aes_key: str = ""
    encrypt_type: int = 1  # 1 = AES-128-ECB


@dataclass
class ImageItem:
    url: str = ""
    media: MediaInfo | None = None
    mid_size: int = 0


@dataclass
class VoiceItem:
    media: MediaInfo | None = None
    voice_size: int = 0
    encode_type: int = 0
    bits_per_sample: int = 0
    sample_rate: int = 0
    playtime: int = 0
    text: str = ""  # speech-to-text from WeChat


@dataclass
class VideoItem:
    media: MediaInfo | None = None
    video_size: int = 0


@dataclass
class FileItem:
    media: MediaInfo | None = None
    file_name: str = ""
    len: str = ""


@dataclass
class MessageItem:
    type: int = ITEM_TYPE_NONE
    text_item: TextItem | None = None
    image_item: ImageItem | None = None
    voice_item: VoiceItem | None = None
    video_item: VideoItem | None = None
    file_item: FileItem | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"type": self.type}
        if self.text_item:
            d["text_item"] = {"text": self.text_item.text}
        if self.image_item:
            d["image_item"] = {"url": self.image_item.url}
            if self.image_item.media:
                d["image_item"]["media"] = {
                    "encrypt_query_param": self.image_item.media.encrypt_query_param,
                    "aes_key": self.image_item.media.aes_key,
                    "encrypt_type": self.image_item.media.encrypt_type,
                }
        if self.voice_item:
            d["voice_item"] = {"text": self.voice_item.text}
            if self.voice_item.media:
                d["voice_item"]["media"] = {
                    "encrypt_query_param": self.voice_item.media.encrypt_query_param,
                    "aes_key": self.voice_item.media.aes_key,
                    "encrypt_type": self.voice_item.media.encrypt_type,
                }
        if self.video_item and self.video_item.media:
            d["video_item"] = {
                "media": {
                    "encrypt_query_param": self.video_item.media.encrypt_query_param,
                    "aes_key": self.video_item.media.aes_key,
                    "encrypt_type": self.video_item.media.encrypt_type,
                }
            }
        if self.file_item:
            d["file_item"] = {"file_name": self.file_item.file_name, "len": self.file_item.len}
            if self.file_item.media:
                d["file_item"]["media"] = {
                    "encrypt_query_param": self.file_item.media.encrypt_query_param,
                    "aes_key": self.file_item.media.aes_key,
                    "encrypt_type": self.file_item.media.encrypt_type,
                }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MessageItem":
        item = cls(type=d.get("type", ITEM_TYPE_NONE))
        if d.get("text_item"):
            item.text_item = TextItem(text=d["text_item"].get("text", ""))
        if d.get("image_item"):
            img = d["image_item"]
            item.image_item = ImageItem(url=img.get("url", ""))
            if img.get("media"):
                item.image_item.media = MediaInfo(
                    encrypt_query_param=img["media"].get("encrypt_query_param", ""),
                    aes_key=img["media"].get("aes_key", ""),
                    encrypt_type=img["media"].get("encrypt_type", 1),
                )
        if d.get("voice_item"):
            voi = d["voice_item"]
            item.voice_item = VoiceItem(text=voi.get("text", ""))
            if voi.get("media"):
                item.voice_item.media = MediaInfo(
                    encrypt_query_param=voi["media"].get("encrypt_query_param", ""),
                    aes_key=voi["media"].get("aes_key", ""),
                    encrypt_type=voi["media"].get("encrypt_type", 1),
                )
        if d.get("video_item"):
            vid = d["video_item"]
            item.video_item = VideoItem()
            if vid.get("media"):
                item.video_item.media = MediaInfo(
                    encrypt_query_param=vid["media"].get("encrypt_query_param", ""),
                    aes_key=vid["media"].get("aes_key", ""),
                    encrypt_type=vid["media"].get("encrypt_type", 1),
                )
        if d.get("file_item"):
            fil = d["file_item"]
            item.file_item = FileItem(
                file_name=fil.get("file_name", ""),
                len=str(fil.get("len", "")),
            )
            if fil.get("media"):
                item.file_item.media = MediaInfo(
                    encrypt_query_param=fil["media"].get("encrypt_query_param", ""),
                    aes_key=fil["media"].get("aes_key", ""),
                    encrypt_type=fil["media"].get("encrypt_type", 1),
                )
        return item


@dataclass
class WeixinMessage:
    seq: int = 0
    message_id: int = 0
    from_user_id: str = ""
    to_user_id: str = ""
    message_type: int = MSG_TYPE_NONE
    message_state: int = MSG_STATE_NEW
    item_list: list[MessageItem] = field(default_factory=list)
    context_token: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WeixinMessage":
        return cls(
            seq=d.get("seq", 0),
            message_id=d.get("message_id", 0),
            from_user_id=d.get("from_user_id", ""),
            to_user_id=d.get("to_user_id", ""),
            message_type=d.get("message_type", MSG_TYPE_NONE),
            message_state=d.get("message_state", MSG_STATE_NEW),
            item_list=[MessageItem.from_dict(i) for i in d.get("item_list", [])],
            context_token=d.get("context_token", ""),
        )

    def extract_text(self) -> str:
        """Extract text content from all text items."""
        parts = []
        for item in self.item_list:
            if item.type == ITEM_TYPE_TEXT and item.text_item:
                parts.append(item.text_item.text)
            elif item.type == ITEM_TYPE_VOICE and item.voice_item and item.voice_item.text:
                parts.append(item.voice_item.text)  # speech-to-text
        return " ".join(parts)

    def has_media(self) -> bool:
        """Check if message contains non-text media."""
        for item in self.item_list:
            if item.type in (ITEM_TYPE_IMAGE, ITEM_TYPE_VOICE, ITEM_TYPE_VIDEO, ITEM_TYPE_FILE):
                return True
        return False


@dataclass
class GetUpdatesResponse:
    ret: int = 0
    err_code: int = 0
    err_msg: str = ""
    msgs: list[WeixinMessage] = field(default_factory=list)
    get_updates_buf: str = ""
    longpolling_timeout_ms: int = 35000


# ═══════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════


class ILinkClient:
    """Async HTTP client for the iLink Bot API."""

    def __init__(self, creds: Credentials | None = None) -> None:
        self._base_url = creds.base_url if creds else DEFAULT_BASE_URL
        self._bot_token = creds.bot_token if creds else ""
        self._bot_id = creds.ilink_bot_id if creds else ""
        self._wechat_uin = self._generate_uin()
        self._client: httpx.AsyncClient | None = None

    # ─── Properties ────────────────────────────────────────────────────

    @property
    def bot_id(self) -> str:
        return self._bot_id

    @property
    def base_url(self) -> str:
        return self._base_url

    # ─── Session management ────────────────────────────────────────────

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # trust_env=False: iLink is a domestic Tencent service — bypass any
            # SOCKS/HTTP proxy env vars (which are typically for VPN/foreign APIs).
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0), trust_env=False)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ─── Auth headers ──────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self._bot_token}",
            "X-WECHAT-UIN": self._wechat_uin,
        }

    @staticmethod
    def _generate_uin() -> str:
        raw = secrets.token_bytes(4)
        n = int.from_bytes(raw, "little")
        return base64.b64encode(str(n).encode()).decode()

    # ─── HTTP helpers ──────────────────────────────────────────────────

    async def _post(self, path: str, body: dict) -> dict:
        client = await self._ensure_client()
        url = f"{self._base_url}{path}"
        resp = await client.post(url, json=body, headers=self._auth_headers())
        if resp.status_code != 200:
            raise ILinkError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _get(self, url: str) -> dict:
        client = await self._ensure_client()
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ILinkError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # ═══════════════════════════════════════════════════════════════════
    # Login flow
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    async def fetch_qrcode() -> QRCodeResponse:
        """Fetch a new QR code for WeChat login (no auth needed)."""
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(QRCODE_URL)
            if resp.status_code != 200:
                raise ILinkError(f"QR code fetch failed: HTTP {resp.status_code}")
            data = resp.json()
            return QRCodeResponse(
                qrcode=data.get("qrcode", ""),
                qrcode_img_content=data.get("qrcode_img_content", ""),
            )

    @staticmethod
    async def poll_qrcode_status(
        qrcode: str,
        on_status: Callable[[str], None] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Credentials:
        """Poll QR code scan status until confirmed or expired.

        Returns Credentials on confirmed, raises on expired/cancelled.
        """
        url = QRCODE_STATUS_URL + qrcode

        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0), trust_env=False) as client:
            while True:
                if cancel_event and cancel_event.is_set():
                    raise ILinkError("Login cancelled")

                try:
                    resp = await client.get(url)
                    data = resp.json()
                except httpx.TimeoutException:
                    continue

                status = data.get("status", "")

                if on_status:
                    on_status(status)

                if status == "confirmed":
                    return Credentials(
                        bot_token=data["bot_token"],
                        ilink_bot_id=data["ilink_bot_id"],
                        base_url=data.get("baseurl", DEFAULT_BASE_URL),
                        ilink_user_id=data["ilink_user_id"],
                    )
                elif status == "expired":
                    raise ILinkError("QR code expired")
                elif status in ("wait", "scaned"):
                    await asyncio.sleep(LOGIN_POLL_INTERVAL)
                else:
                    await asyncio.sleep(LOGIN_POLL_INTERVAL)

    # ═══════════════════════════════════════════════════════════════════
    # Message receiving (long-poll)
    # ═══════════════════════════════════════════════════════════════════

    async def get_updates(self, buf: str = "") -> GetUpdatesResponse:
        """Long-poll for new messages. Returns when messages arrive or timeout."""
        body = {
            "get_updates_buf": buf,
            "base_info": {"channel_version": "1.0.0"},
        }
        data = await self._post("/ilink/bot/getupdates", body)
        return GetUpdatesResponse(
            ret=data.get("ret", 0),
            err_code=data.get("errcode", 0),
            err_msg=data.get("errmsg", ""),
            msgs=[WeixinMessage.from_dict(m) for m in data.get("msgs", [])],
            get_updates_buf=data.get("get_updates_buf", ""),
            longpolling_timeout_ms=data.get("longpolling_timeout_ms", 35000),
        )

    # ═══════════════════════════════════════════════════════════════════
    # Message sending
    # ═══════════════════════════════════════════════════════════════════

    async def send_message(
        self,
        to_user_id: str,
        item_list: list[MessageItem],
        context_token: str = "",
        from_user_id: str | None = None,
        message_state: int = MSG_STATE_FINISH,
    ) -> bool:
        """Send a message to a WeChat user.

        Args:
            to_user_id: Recipient WeChat user ID
            item_list: Message items to send (text, image, etc.)
            context_token: User's context token from last message
            from_user_id: Sender (defaults to bot_id)
            message_state: 0=new, 1=generating, 2=finish (default)
        """
        body = {
            "msg": {
                "from_user_id": from_user_id or self._bot_id,
                "to_user_id": to_user_id,
                "client_id": secrets.token_hex(8),
                "message_type": MSG_TYPE_BOT,
                "message_state": message_state,
                "item_list": [item.to_dict() for item in item_list],
                "context_token": context_token,
            },
            "base_info": {"channel_version": "1.0.0"},
        }
        data = await self._post("/ilink/bot/sendmessage", body)
        if data.get("ret", -1) != 0:
            raise ILinkError(f"sendmessage failed: {data.get('errmsg', 'unknown')}")
        return True

    async def send_text(
        self,
        to_user_id: str,
        text: str,
        context_token: str = "",
    ) -> bool:
        """Send a text message."""
        return await self.send_message(
            to_user_id=to_user_id,
            item_list=[MessageItem(type=ITEM_TYPE_TEXT, text_item=TextItem(text=text))],
            context_token=context_token,
        )

    async def send_image(
        self,
        to_user_id: str,
        image_url: str,
        context_token: str = "",
    ) -> bool:
        """Send an image by URL."""
        return await self.send_message(
            to_user_id=to_user_id,
            item_list=[MessageItem(type=ITEM_TYPE_IMAGE, image_item=ImageItem(url=image_url))],
            context_token=context_token,
        )

    # ═══════════════════════════════════════════════════════════════════
    # Typing indicator
    # ═══════════════════════════════════════════════════════════════════

    async def send_typing(
        self,
        user_id: str,
        typing_ticket: str,
        status: int = TYPING_START,
    ) -> bool:
        """Send typing indicator to a user.

        typing_ticket must be fetched from get_config() first.
        """
        body = {
            "ilink_user_id": user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": {},
        }
        data = await self._post("/ilink/bot/sendtyping", body)
        return data.get("ret", -1) == 0

    async def get_config(self, user_id: str, context_token: str = "") -> dict:
        """Fetch bot config for a user — includes typing_ticket."""
        body = {
            "ilink_user_id": user_id,
            "context_token": context_token,
            "base_info": {},
        }
        return await self._post("/ilink/bot/getconfig", body)

    async def get_typing_ticket(self, user_id: str, context_token: str = "") -> str:
        """Fetch the typing ticket needed for send_typing."""
        config = await self.get_config(user_id, context_token)
        return config.get("typing_ticket", "")

    # ═══════════════════════════════════════════════════════════════════
    # CDN media upload
    # ═══════════════════════════════════════════════════════════════════

    async def upload_media(
        self,
        file_data: bytes,
        file_name: str,
        to_user_id: str,
        media_type: int = CDN_MEDIA_IMAGE,
    ) -> MediaInfo:
        """Upload media to WeChat CDN.

        Returns MediaInfo with encryption details for send_message.
        """
        # Generate AES key (for AES-128-ECB)
        aes_key = secrets.token_bytes(16)
        aes_key_b64 = base64.b64encode(aes_key).decode()

        # Encrypt file content with AES-128-ECB
        encrypted = self._aes_ecb_encrypt(aes_key, file_data)
        encrypted_size = len(encrypted)

        file_md5 = hashlib.md5(file_data).hexdigest()

        # Get upload URL
        upload_req = {
            "filekey": f"{secrets.token_hex(16)}_{file_name}",
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": len(file_data),
            "rawfilemd5": file_md5,
            "filesize": encrypted_size,
            "no_need_thumb": False,
            "aeskey": aes_key_b64,
            "base_info": {},
        }

        upload_info = await self._post("/ilink/bot/getuploadurl", upload_req)
        if upload_info.get("ret", -1) != 0:
            raise ILinkError(f"getuploadurl failed: {upload_info.get('errmsg', 'unknown')}")

        upload_url = upload_info.get("upload_full_url", "")
        if not upload_url:
            raise ILinkError("No upload URL returned")

        # Upload to CDN
        client = await self._ensure_client()
        resp = await client.put(
            upload_url,
            content=encrypted,
            headers={"Content-Type": "application/octet-stream"},
        )
        if resp.status_code not in (200, 201, 204):
            raise ILinkError(f"CDN upload failed: HTTP {resp.status_code}")

        return MediaInfo(
            encrypt_query_param=upload_info.get("upload_param", ""),
            aes_key=aes_key_b64,
            encrypt_type=1,  # AES-128-ECB
        )

    @staticmethod
    def _aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
        """AES-128-ECB encrypt with PKCS7 padding.

        Requires 'cryptography' package. Falls back to pure-Python impl
        if unavailable (slow but works for small files).
        """
        # PKCS7 padding
        block_size = 16
        pad_len = block_size - (len(data) % block_size)
        padded = data + bytes([pad_len] * pad_len)

        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend

            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            encryptor = cipher.encryptor()
            return encryptor.update(padded) + encryptor.finalize()
        except ImportError:
            # Pure-Python fallback (PyCryptodome-compatible via pyaes if installed)
            try:
                import pyaes
                aes = pyaes.AESModeOfOperationECB(key)
                result = bytearray()
                for i in range(0, len(padded), block_size):
                    result.extend(aes.encrypt(padded[i:i + block_size]))
                return bytes(result)
            except ImportError:
                raise ILinkError(
                    "Media upload requires 'cryptography' or 'pyaes' package. "
                    "Install with: pip install cryptography"
                )


# ═══════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════


class ILinkError(Exception):
    """Base error for iLink API failures."""

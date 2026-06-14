"""WeChat iLink integration — native WeChat bot connectivity.

Uses Tencent's iLink Bot API (not XML webhook).  QR code login,
long-poll message receiving, and message/media sending.

Does NOT touch the web WebSocket flow — runs independently via
background asyncio tasks.
"""

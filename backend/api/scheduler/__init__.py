"""Scheduled task system — agent-invoked scheduling via MCP.

Architecture:
  1. stdio MCP server (inside Docker container) — agent calls register_schedule tool,
     writes task JSON to /workspace/.vera/schedules/pending/
  2. Host dispatcher (asyncio loop in Vera backend) — scans pending/ every 30s,
     at cron time invokes the agent through the normal adapter pipeline
  3. Results persisted as messages in the session (user sees them next time they open chat)
"""

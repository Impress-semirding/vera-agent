#!/usr/bin/env python3
"""Vera Scheduler MCP Server — stdio, runs inside the agent container.

Agent calls this to register/manage scheduled tasks. Writes to the host DB
via HTTP API (localhost:18080). Uses VERA_TOKEN for auth.
"""

import json
import os
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vera-scheduler")

BACKEND_URL = os.environ.get("VERA_BACKEND_URL", "http://127.0.0.1:18080/api/v1")
VERA_TOKEN = os.environ.get("VERA_TOKEN", "")
VERA_AGENT_ID = os.environ.get("VERA_AGENT_ID", "")
VERA_SESSION_ID = os.environ.get("VERA_SESSION_ID", "")


def _api(method: str, path: str, data: dict | None = None) -> dict:
    """Call Vera REST API."""
    url = f"{BACKEND_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if VERA_TOKEN:
        req.add_header("Authorization", f"Bearer {VERA_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        try:
            err_data = json.loads(err_body)
            msg = err_data.get("detail", err_body)
        except Exception:
            msg = err_body
        return {"code": e.code, "message": msg}
    except Exception as e:
        return {"code": -1, "message": str(e)}


def _validate_cron(expr: str) -> bool:
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for i, part in enumerate(parts):
        lo, hi = ranges[i]
        for token in part.split(","):
            token = token.strip().replace("*/", "").split("/")[0].split("-")[0]
            if token == "*" or token == "":
                continue
            try:
                v = int(token)
                if v < lo or v > hi:
                    return False
            except ValueError:
                return False
    return True


@mcp.tool()
def register_schedule(prompt: str, cron: str, name: str = "", timeout: int = 1200) -> dict:
    """注册定时任务，到时间会自动唤醒当前 agent 执行 prompt。

    Args:
        prompt: 触发时发给 agent 的动作描述（用户原话去掉时间部分）
        cron: 5 段 cron「分 时 日 月 周」，0=周日。如 "0 8 * * *" = 每天8点
        name: 任务名称，方便识别
        timeout: 超时秒数，默认 1200（20分钟）
    """
    if not _validate_cron(cron):
        return {"success": False, "error": f"无效的 cron: {cron}"}
    if not VERA_AGENT_ID:
        return {"success": False, "error": "缺少 VERA_AGENT_ID 环境变量"}

    resp = _api("POST", f"/agents/{VERA_AGENT_ID}/schedules/chat", {
        "name": name or f"任务_{prompt[:20]}",
        "prompt": prompt,
        "cron": cron,
        "timeout": timeout,
        "session_id": VERA_SESSION_ID or None,
    })
    if resp.get("code") == 0:
        d = resp.get("data", {})
        return {"success": True, "task_id": d.get("id", ""), "message": f"已注册: {d.get('name','')}，周期: {cron}"}
    return {"success": False, "error": resp.get("message", "注册失败")}


@mcp.tool()
def list_schedules() -> list:
    """列出当前 agent 的所有定时任务。"""
    resp = _api("GET", f"/agents/{VERA_AGENT_ID}/schedules")
    if resp.get("code") == 0:
        return resp.get("data", [])
    return []


@mcp.tool()
def delete_schedule(task_id: str) -> dict:
    """删除定时任务。"""
    resp = _api("DELETE", f"/agents/{VERA_AGENT_ID}/schedules/{task_id}")
    if resp.get("code") == 0:
        return {"success": True, "message": f"任务 {task_id} 已删除"}
    return {"success": False, "error": resp.get("message", "删除失败")}


@mcp.tool()
def pause_schedule(task_id: str) -> dict:
    """暂停定时任务。"""
    resp = _api("PUT", f"/agents/{VERA_AGENT_ID}/schedules/{task_id}", {"enabled": False})
    if resp.get("code") == 0:
        return {"success": True, "message": f"任务 {task_id} 已暂停"}
    return {"success": False, "error": resp.get("message", "暂停失败")}


@mcp.tool()
def resume_schedule(task_id: str) -> dict:
    """恢复定时任务。"""
    resp = _api("PUT", f"/agents/{VERA_AGENT_ID}/schedules/{task_id}", {"enabled": True})
    if resp.get("code") == 0:
        return {"success": True, "message": f"任务 {task_id} 已恢复"}
    return {"success": False, "error": resp.get("message", "恢复失败")}


@mcp.tool()
def get_schedule_result(task_id: str) -> dict:
    """查看任务最近一次执行结果。"""
    resp = _api("GET", f"/agents/{VERA_AGENT_ID}/schedules")
    if resp.get("code") == 0:
        for t in resp.get("data", []):
            if t.get("id") == task_id:
                return {
                    "success": True,
                    "name": t.get("name", ""),
                    "status": t.get("status", ""),
                    "last_run": t.get("lastRunAt", "从未执行"),
                    "last_status": t.get("lastStatus", ""),
                    "last_result": t.get("lastResult", ""),
                    "next_run": t.get("nextRunAt", ""),
                }
    return {"success": False, "error": f"任务 {task_id} 不存在"}


if __name__ == "__main__":
    mcp.run(transport="stdio")

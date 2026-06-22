"""Scheduled task dispatcher — host-side asyncio loop.

Scans DB for due tasks every 30 seconds. When a task is due:
  1. (optional) Run Python script, capture output
  2. Invoke agent with prompt (+ script output)
  3. Persist result as session messages
  4. Push result to user (WS if connected, WeChat if WeChat session)
  5. Update task status in DB
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from api.scheduler.cron_util import next_run, _now as cron_now

logger = logging.getLogger("scheduler")

SCAN_INTERVAL = 30
TASK_TIMEOUT_DEFAULT = 1200  # 20 minutes
MAX_FAILS = 3


async def scheduler_loop() -> None:
    """Main loop — scan DB for due tasks and execute them."""
    try:
        await _recover_stuck_tasks()
    except Exception as exc:
        logger.error(f"[scheduler] failed to recover stuck tasks: {exc}")
    logger.info("[scheduler] dispatcher started")
    while True:
        try:
            await _scan_and_dispatch()
        except Exception as exc:
            logger.exception(f"[scheduler] scan error: {exc}")
        await asyncio.sleep(SCAN_INTERVAL)


async def _recover_stuck_tasks() -> None:
    """On startup, reset any tasks that were mid-execution when dispatcher crashed."""
    from api.database import async_session
    from api.models import models as M
    from sqlalchemy import select

    async with async_session() as db:
        stuck = (await db.execute(
            select(M.ScheduledTask).where(M.ScheduledTask.status == "running")
        )).scalars().all()
        for task in stuck:
            task.status = "active"
            logger.warning(f"[scheduler] recovered stuck task: {task.name} ({task.id})")
        if stuck:
            await db.commit()


async def _scan_and_dispatch() -> None:
    from api.database import async_session
    from api.models import models as M
    from sqlalchemy import select

    now = cron_now()
    async with async_session() as db:
        due = (await db.execute(
            select(M.ScheduledTask).where(
                M.ScheduledTask.enabled.is_(True),
                M.ScheduledTask.status == "active",
                M.ScheduledTask.next_run_at.is_not(None),
                M.ScheduledTask.next_run_at <= now,
            )
        )).scalars().all()

        for task in due:
            task.status = "running"
            await db.commit()
            asyncio.create_task(_execute_and_finalize(task.id))


async def _execute_and_finalize(task_id: str) -> None:
    from api.database import async_session
    from api.models import models as M
    from sqlalchemy import select

    # Reload task
    async with async_session() as db:
        task = (await db.execute(
            select(M.ScheduledTask).where(M.ScheduledTask.id == task_id)
        )).scalar_one_or_none()
        if task is None:
            return

    await _execute_task(task)

    # Finalize: compute next run, update status
    async with async_session() as db:
        task = (await db.execute(
            select(M.ScheduledTask).where(M.ScheduledTask.id == task_id)
        )).scalar_one_or_none()
        if task is None:
            return
        task.last_run_at = cron_now()
        try:
            task.next_run_at = next_run(task.cron)
            # Only reset fail_count on explicit success; preserve it on failure
            # so the MAX_FAILS auto-disable works across runs.
            if task.last_status == "success":
                task.fail_count = 0
            if task.status == "running":
                task.status = "active"
        except Exception:
            task.status = "failed"
            task.enabled = False
        await db.commit()


async def _execute_task(task) -> None:
    """Execute a scheduled task: (optional script) → agent → persist → push."""
    from agent_runtime.registry import create_adapter
    from api.database import async_session
    from api.models import models as M
    from api.routers.chat import _persist_message
    from api.util import new_id
    from sqlalchemy import select

    agent_id = task.agent_id
    user_id = task.user_id or "system"
    session_id = task.session_id
    prompt = task.prompt
    timeout = task.timeout or TASK_TIMEOUT_DEFAULT

    logger.info(f"[scheduler] executing task={task.name} agent={agent_id}")

    # Resolve or create session
    if not session_id:
        async with async_session() as db:
            session = M.Session(
                id=new_id(),
                agent_id=agent_id,
                name=f"[定时] {task.name}",
                created_by=user_id,
            )
            db.add(session)
            await db.commit()
            session_id = session.id
            async with async_session() as db2:
                t = (await db2.execute(select(M.ScheduledTask).where(M.ScheduledTask.id == task.id))).scalar_one_or_none()
                if t:
                    t.session_id = session_id
                    await db2.commit()

    # ── Step 1: Run script (if task_type=script+agent) ──────────────
    script_output = ""
    if task.script_content and task.script_name:
        script_output = await _run_script(task, timeout)
        await _persist_message(session_id, "user",
            f"[定时任务·脚本] {task.name}\n执行 {task.script_name}，输出：\n{script_output[:500]}")

    # ── Step 2: Invoke agent ─────────────────────────────────────────
    full_prompt = prompt
    if script_output:
        full_prompt = f"{prompt}\n\n以下是脚本执行结果，请分析：\n{script_output}"

    # Load agent + model config
    async with async_session() as db:
        agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
        if agent is None:
            await _update_task_result(task.id, "failed", "Agent 不存在")
            return
        model_config = (await db.execute(
            select(M.ModelConfig).where(M.ModelConfig.model_id == agent.model, M.ModelConfig.enabled.is_(True))
        )).scalar_one_or_none()
        if model_config is None:
            model_config = (await db.execute(
                select(M.ModelConfig).where(M.ModelConfig.enabled.is_(True)).limit(1)
            )).scalar_one_or_none()
        if model_config is None:
            await _update_task_result(task.id, "failed", "无可用模型配置")
            return

    # Persist prompt
    await _persist_message(session_id, "user", f"[定时任务] {task.name}\n{full_prompt}")

    # Create adapter and run
    adapter = None
    reply = ""
    agent_error = ""
    try:
        adapter = await create_adapter(agent.mode, agent_id, user_id, session_id, model_config)
        await adapter.send(full_prompt)

        content_parts: list[str] = []
        final_reached = False

        async def _collect():
            nonlocal final_reached, agent_error
            async for event in adapter.read_deltas():
                etype = event.get("type", "")
                if etype == "model_delta" and event.get("channel") == "content":
                    content_parts.append(event.get("text", ""))
                elif etype == "model_final":
                    final_reached = True
                    break
                elif etype == "error":
                    agent_error = event.get("message", "Agent 错误")
                    break

        await asyncio.wait_for(_collect(), timeout=timeout)
        reply = "".join(content_parts)

    except asyncio.TimeoutError:
        reply = f"[定时任务执行超时（{timeout}秒）]"
        await _update_task_result(task.id, "timeout", f"超时（{timeout}秒）")
        agent_error = "timeout"
    except Exception as exc:
        reply = f"[定时任务执行失败] {exc}"
        await _update_task_result(task.id, "failed", str(exc)[:200])
        agent_error = str(exc)[:200]
    else:
        if agent_error:
            await _update_task_result(task.id, "failed", f"error: {agent_error}")
        elif final_reached:
            await _update_task_result(task.id, "success", reply[:200] if reply else "(无回复)")
        else:
            await _update_task_result(task.id, "failed", "连接意外断开（无 model_final）")
    finally:
        if adapter:
            try:
                await adapter.close()
            except Exception:
                pass

    # ── Step 3: Persist assistant reply ──────────────────────────────
    await _persist_message(session_id, "assistant", reply or "(无回复)")

    # ── Step 4: Push result to user ──────────────────────────────────
    await _push_result(agent_id, user_id, session_id, task.name, reply)


async def _run_script(task, timeout: int) -> str:
    """Run a Python script in a one-off Docker container, return stdout."""
    from agent_runtime.claude.config import _WORKSPACE_BASE

    script_dir = os.path.join(_WORKSPACE_BASE, task.agent_id, task.user_id or "system", ".vera", "scripts")
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, task.script_name)

    # Write script
    with open(script_path, "w") as f:
        f.write(task.script_content)
    os.chmod(script_dir, 0o777)
    os.chmod(script_path, 0o777)

    # Run in one-off container
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm",
            "-v", f"{os.path.abspath(script_dir)}:/scripts",
            "-v", f"{os.path.abspath(os.path.join(_WORKSPACE_BASE, task.agent_id, task.user_id or 'system'))}:/workspace",
            "--network", "host",
            os.environ.get("AGENT_DOCKER_IMAGE", "vera-agent-runner:latest"),
            "python3", f"/scripts/{task.script_name}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            output += f"\n[STDERR] {stderr.decode('utf-8', errors='replace')[:500]}"
        logger.info(f"[scheduler] script {task.script_name} output length={len(output)}")
        return output
    except asyncio.TimeoutError:
        proc.kill()
        return f"[脚本执行超时（{timeout}秒）]"
    except Exception as exc:
        return f"[脚本执行失败] {exc}"


async def _push_result(agent_id: str, user_id: str, session_id: str, task_name: str, reply: str) -> None:
    """Push task result to user via WS (if connected) or WeChat (if WeChat session)."""
    if not reply:
        return

    # ── 4a. Try WS push (if user has active connection) ──────────────
    try:
        from api.routers.chat import _user_ws
        key = f"{user_id}:{agent_id}"
        ws = _user_ws.get(key)
        if ws is not None:
            await ws.send_json({
                "type": "model_final",
                "sessionId": session_id,
                "content": reply,
                "reasoningContent": "",
                "turnId": f"sched-{int(cron_now().timestamp())}",
            })
            logger.info(f"[scheduler] pushed result via WS to {user_id}")
            return
    except Exception as exc:
        logger.debug(f"[scheduler] WS push failed: {exc}")

    # ── 4b. Try WeChat push (if session is a WeChat session) ─────────
    try:
        from api.database import async_session
        from api.models import models as M
        from sqlalchemy import select

        async with async_session() as db:
            session = (await db.execute(
                select(M.Session).where(M.Session.id == session_id)
            )).scalar_one_or_none()

        if session and session.name and session.name.startswith("wechat_"):
            wechat_user_id = session.name.replace("wechat_", "")
            from agent_runtime.wechat.monitor import get_monitor
            agent_monitor = get_monitor(agent_id)
            if agent_monitor:
                await agent_monitor._handler._send_text(wechat_user_id, f"[定时任务] {task_name}\n{reply}")
                logger.info(f"[scheduler] pushed result via WeChat to {wechat_user_id}")
                return
    except Exception as exc:
        logger.debug(f"[scheduler] WeChat push failed: {exc}")

    logger.info(f"[scheduler] result saved to session {session_id} (no live push)")


async def _update_task_result(task_id: str, status: str, result: str) -> None:
    from api.database import async_session
    from api.models import models as M
    from sqlalchemy import select

    async with async_session() as db:
        task = (await db.execute(
            select(M.ScheduledTask).where(M.ScheduledTask.id == task_id)
        )).scalar_one_or_none()
        if task is None:
            return
        task.last_status = status
        task.last_result = result
        if status in ("failed", "timeout"):
            task.fail_count += 1
            if task.fail_count >= MAX_FAILS:
                task.status = "failed"
                task.enabled = False
                logger.warning(f"[scheduler] task {task_id} auto-disabled after {MAX_FAILS} failures")
        await db.commit()

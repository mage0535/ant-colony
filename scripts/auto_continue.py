#!/usr/bin/env python3
"""Auto-continue: every 5 min checks + advances dev work.

Loop:
  1. Check gateway idle?
  2. Load current phase from state.json
  3. If no phase / all done → read handoff.md next-steps → generate new phases
  4. Execute current phase (shell command or report "needs AI")
  5. Record result in state.json + handoff.md
  6. If phase requires AI → log to handoff so next AI session picks it up
"""

import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
              logging.StreamHandler()],
)
logger = logging.getLogger("auto_continue")

STATE_FILE = BASE / "data" / "state.json"
HANDOFF_FILE = BASE / "docs" / "handoff.md"

# ---- phases that CAN run autonomously (shell commands only) ----
AUTO_PHASES: dict[str, list[dict]] = {
    "restart_dashboard": [
        {"cmd": ["sudo", "systemctl", "restart", "ant-colony-dashboard.service"], "desc": "重启仪表盘"},
    ],
    "run_tests": [
        {"cmd": ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"], "desc": "运行全部测试", "timeout": 120},
    ],
    "install_v2ray": [
        {"cmd": ["sudo", "apt-get", "install", "-y", "v2ray"], "desc": "安装 v2ray", "timeout": 60},
    ],
}

NEEDS_AI_MSG = "[需要 AI 会话处理]"


def check_gateway() -> dict:
    try:
        t = json.loads(urllib.request.urlopen("http://127.0.0.1:18090/tasks", timeout=5).read().decode())
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:18090/drafts", timeout=5).read().decode())
        tasks = t.get("tasks", [])
        drafts = d.get("drafts", [])
        active = [x for x in tasks if x["status"] in ("in_progress", "confirmed", "blocked")]
        return {"up": True, "tasks": len(tasks), "drafts": len(drafts), "active": len(active),
                "idle": len(active) == 0 and len(drafts) == 0}
    except Exception as e:
        return {"up": False, "error": str(e), "idle": False}


def check_services() -> dict:
    """Check all systemd services, return {name: active|dead}."""
    services = ["ant-colony-gateway", "ant-colony-callback", "ant-colony-dashboard", "v2ray", "docker"]
    result = {}
    for svc in services:
        try:
            r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
            result[svc] = r.stdout.strip()
        except Exception:
            result[svc] = "unknown"
    return result


def parse_handoff_next_steps() -> list[str]:
    """Read handoff.md, extract ### 下一步建议 list items."""
    if not HANDOFF_FILE.exists():
        return ["创建项目初始化"]
    text = HANDOFF_FILE.read_text(encoding="utf-8")
    # Find the latest "下一步建议" section
    sections = re.split(r'^### ', text, flags=re.MULTILINE)
    for sec in reversed(sections):
        if sec.startswith("下一步建议"):
            items = re.findall(r'^\d+\.\s*(.*)', sec, re.MULTILINE)
            return [item.strip() for item in items]
    return ["handoff.md 缺少下一步建议"]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"phases": [], "idx": 0, "sub": 0}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE), timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[:2000]
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except FileNotFoundError as e:
        return -2, str(e)


def generate_phases_from_handoff() -> list[dict]:
    """Turn handoff next-steps into phases; annotate needs_ai where appropriate."""
    steps = parse_handoff_next_steps()
    phases = []
    for s in steps:
        s_lower = s.strip().lower()
        # Only match the FIRST 30 chars to avoid false positives from long descriptions
        s_head = s_lower[:30]
        auto_key = None
        if any(kw in s_head for kw in ["重启", "restart", "同步", "sync", "重载"]):
            auto_key = "restart_dashboard"
        elif any(kw in s_head for kw in ["测试", "test", "pytest", "运行测试"]):
            auto_key = "run_tests"
        elif any(kw in s_head for kw in ["安装", "install "]):
            auto_key = "install_v2ray"

        if auto_key:
            phases.append({"desc": s, "auto": auto_key, "sub": 0, "needs_ai": False})
        else:
            phases.append({"desc": s, "auto": None, "sub": 0, "needs_ai": True})

    phases.append({"desc": "全部阶段完成", "auto": None, "sub": 0, "needs_ai": False, "is_done": True})
    return phases


def execute_auto_phase(phase: dict) -> tuple[bool, str]:
    """Run an automated phase. Returns (done, message)."""
    auto_key = phase.get("auto")
    if not auto_key or auto_key not in AUTO_PHASES:
        return True, "nothing to run"

    steps = AUTO_PHASES[auto_key]
    sub = phase.get("sub", 0)

    if sub >= len(steps):
        return True, "all sub-steps done"

    step = steps[sub]
    timeout = step.get("timeout", 60)
    code, out = run(step["cmd"], timeout=timeout)
    if code == 0:
        return True, f"OK: {step['desc']}"
    return False, f"FAIL: {step['desc']}: {out[:200]}"


def append_to_handoff(section: str, content: str) -> None:
    """Append a note to handoff.md so next AI session sees it."""
    if not HANDOFF_FILE.exists():
        return
    text = HANDOFF_FILE.read_text(encoding="utf-8")
    text += f"\n\n### auto-continue: {section}\n{content}\n"
    HANDOFF_FILE.write_text(text, encoding="utf-8")


def main() -> None:
    status = check_gateway()
    svc_status = check_services()
    logger.info("Status: up=%s, active=%s, drafts=%s, idle=%s",
                status.get("up"), status.get("active"), status.get("drafts"), status.get("idle"))
    logger.info("Services: %s", svc_status)

    if not status["idle"]:
        logger.info("网关有活跃任务 — 等待下次检查")
        return

    state = load_state()
    phases = state.get("phases", [])
    idx = state.get("idx", 0)

    # If no phases or all done → regenerate from handoff
    if not phases or idx >= len(phases):
        logger.info("阶段列表为空或已全部完成，从 handoff.md 重新生成...")
        phases = generate_phases_from_handoff()
        state["phases"] = phases
        state["idx"] = 0
        state["sub"] = 0
        save_state(state)
        logger.info("生成 %d 个新阶段", len(phases))
        # Log next-steps to handoff for AI visibility
        next_steps = [p["desc"] for p in phases if not p.get("is_done")]
        append_to_handoff("新阶段已生成", "\n".join(f"- {s}" for s in next_steps))

    current = phases[idx]
    desc = current["desc"]

    if current.get("is_done"):
        logger.info("全部阶段完成。5分钟后重新检查 handoff.md 是否有更新。")
        # Reset so next cycle will re-read handoff
        state["idx"] = len(phases)
        save_state(state)
        return

    if current.get("needs_ai"):
        logger.info("阶段 %d/%d [需 AI]: %s — 自动跳过，等待 AI 会话处理", idx + 1, len(phases), desc)
        append_to_handoff("等待 AI 处理", f"阶段 {idx+1}: {desc}")
        # Mark as completed so next cycle moves on
        state["idx"] = idx + 1
        state["sub"] = 0
        save_state(state)
        return

    # Auto phase
    logger.info("阶段 %d/%d [自动]: %s", idx + 1, len(phases), desc)
    done, msg = execute_auto_phase(current)
    if done:
        logger.info("完成: %s", msg)
        state["idx"] = idx + 1
        state["sub"] = 0
    else:
        logger.warning("失败: %s", msg)
        state["sub"] = current.get("sub", 0) + 1
        if state["sub"] > 3:
            logger.error("阶段 %s 重试 3 次仍失败，跳过", desc)
            state["idx"] = idx + 1
            state["sub"] = 0

    save_state(state)


if __name__ == "__main__":
    main()

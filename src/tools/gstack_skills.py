"""GStack-inspired methodology tools for software development lifecycle.

Implements key skills from gstack (by Garry Tan, YC CEO) as Agent tools:

- office_hours: Product discovery with forcing questions
- review_doc: Systematic document/code review methodology
- investigate: Root cause debugging protocol
- spec: Turn vague intent into executable specifications
- retro: Team retrospective analysis
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def office_hours(goal: str = "", context: str = "") -> str:
    """YC Office Hours — 6 forcing questions that reframe the problem.

    Returns structured questions the Agent can use to guide the user.
    """
    questions = [
        "【问题 1/6】你具体想解决什么问题？请给出一个真实、具体的例子。",
        "【问题 2/6】目前你是怎么做的？痛点在哪里？",
        "【问题 3/6】你设想的理想解决方案是什么样的？",
        "【问题 4/6】如果不做这件事，有什么替代方案？",
        "【问题 5/6】你觉得最大的风险或不确定因素是什么？",
        "【问题 6/6】这件事的紧急程度和影响范围？",
    ]
    return f"## 产品探索 (Office Hours)\n\n目标: {goal or '待确认'}\n\n请逐条回答以下 6 个问题：\n\n" + "\n\n".join(f"{q}" for q in questions)


def review_doc(doc_type: str = "general", content: str = "") -> str:
    """Systematic review methodology.

    Different review modes based on doc_type:
    - general: completeness + clarity + correctness
    - code: security + performance + maintainability
    - design: consistency + usability + accessibility
    """
    templates = {
        "general": ["完整性检查", "清晰度检查", "准确性检查", "一致性和可行性"],
        "code": ["安全审查", "性能评估", "可维护性分析", "边界条件检查"],
        "design": ["视觉一致性", "可用性评估", "无障碍检查", "交互流程"],
    }
    checks = templates.get(doc_type, templates["general"])
    lines = ["## 审查方法论\n"]
    if content:
        lines.append(f"审查对象: {content[:200]}...\n" if len(content) > 200 else f"审查对象:\n{content}\n")
    lines.append("审查维度：")
    for i, check in enumerate(checks, 1):
        lines.append(f"  {i}. {check} — 逐项评估，发现问题自动修复，并生成回归测试")
    lines.append("\n工作流：")
    lines.append("  1. 逐维度审查 → 2. 标记问题 (auto-fix / ask) → 3. 修复 → 4. 回归验证")
    return "\n".join(lines)


def investigate(issue: str = "", context: str = "") -> str:
    """Root cause investigation protocol.

    Systematic debugging: observe → hypothesize → test → conclude.
    """
    return (
        f"## 根因调查 (Investigate)\n\n"
        f"问题: {issue or '待调查'}\n\n"
        "协议规则：\n"
        "1. 【铁律】在根因确认之前，禁止提出任何修复方案\n"
        "2. 遵循流程: 观察现象 → 追踪数据流 → 提出假设 → 验证/否定 → 收敛\n"
        "3. 如果连续 3 次修复失败，停止并重新调查\n"
        "4. 每次验证后记录: 做了什么、结果如何、下一个假设\n\n"
        "开始调查：\n"
        "  1. 描述观察到的问题现象\n"
        "  2. 追溯数据流/调用链\n"
        "  3. 提出假设\n"
        "  4. 验证或否定\n"
        "  5. 收敛到根因"
    )


def spec_tool(goal: str = "") -> str:
    """Turn vague intent into an executable spec.

    Five-phase methodology: why → scope → technical → draft → file.
    """
    return (
        f"## 需求规格化 (Spec)\n\n"
        f"目标: {goal or '待确认'}\n\n"
        "五阶段流程：\n"
        "1. 【为什么】背景、动机、成功标准\n"
        "     - 为什么要做？\n"
        "     - 成功的定义是什么？\n"
        "2. 【范围】功能边界、排除项\n"
        "     - 包含哪些功能？\n"
        "     - 明确不做什么？\n"
        "3. 【技术方案】数据流、状态机、接口定义\n"
        "     - 架构图（ASCII）\n"
        "     - 数据流\n"
        "     - 接口定义\n"
        "4. 【草案】整合成文档\n"
        "5. 【定稿】评审后定稿\n"
        "完成后可使用 review_doc 审查规格。"
    )


def retro_tool(period: str = "本周", data: str = "") -> str:
    """Team retrospective analysis.

    Analyzes what went well, what could improve, and action items.
    """
    return (
        f"## 团队回顾 (Retro)\n\n"
        f"周期: {period}\n\n"
        "回顾框架：\n"
        "1. **做得好** — 哪些地方值得保持？\n"
        "2. **可以改进** — 哪些地方需要调整？\n"
        "3. **行动项** — 接下来具体做什么？\n"
        "4. **趋势** — 对比上次回顾，是否有改善？"
    )

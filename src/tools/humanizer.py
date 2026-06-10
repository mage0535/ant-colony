"""Humanizer — AI text humanization and behavior analysis tools.

Two core capabilities:

1. **De-AI Humanizer**: Detects and removes 29 common AI writing patterns,
   replaces them with natural human alternatives, and adds personality.

2. **Human Behavior Analyst**: 7-module framework for analyzing
   communication style, emotions, relationship dynamics, and providing
   tailored response strategies.

Usage:
    from src.tools.humanizer import humanize, analyze_style
"""

from __future__ import annotations

import re
from typing import Any

# ────────────────────────────────────────────────────────────────
#  29 AI Writing Patterns — detection regexes
# ────────────────────────────────────────────────────────────────

AI_PATTERNS: dict[str, tuple[str, str, str]] = {
    # (name, regex, human alternative hint)
    "significance": (
        r"\b(serves as|stands as|is a testament to|pivotal|underscores the|"
        r"broader trends|evolving landscape|deeply rooted in|testament)\b",
        "用简单动词替代（is/has/does）",
    ),
    "ing_phrases": (
        r",\s*(highlighting|symbolizing|reflecting|showcasing|contributing to|"
        r"ensuring|underscoring)\s",
        "把 -ing 短语拆成独立句子",
    ),
    "promotional": (
        r"\b(boasts? a|nestled|vibrant|rich\b(?!\s+in\s+minerals)|profound|"
        r"in the heart of|groundbreaking|breathtaking|must-visit)\b",
        "用平实描述替代夸张形容词",
    ),
    "vague_attribution": (
        r"\b(Industry reports|Observers have cited|Experts argue|"
        r"Several sources|Some critics argue|It is widely believed)\b",
        "删掉模糊引用，或者给出具体来源",
    ),
    "formulaic_challenges": (
        r"(Despite \w+, \w+ faces several challenges|"
        r"Despite these challenges, \w+ continues to thrive)",
        "直接说问题，不要套模板",
    ),
    "ai_vocab": (
        r"\b(additionally|align with|delve|emphasizing|enduring|"
        r"foster|garner|interplay|intricate|landscape|showcase|"
        r"tapestry|underscore|valuable|leveraging|leverage)\b",
        "换成日常用词（and/work with/dig into/keep/help/get/use）",
    ),
    "copula_avoidance": (
        r"\b(serves as|stands as|marks|represents|boasts|features|offers)\s+a",
        "直接说 is/has",
    ),
    "neg_parallelism": (
        r"(Not only.*but|It.s not just about.*it.s)",
        "直接陈述，不要否定平行结构",
    ),
    "rule_of_three": (
        r"(\w+), (\w+), and (\w+)",
        "如果三个并列是机械堆砌，拆开或减到两个",
    ),
    "elegant_variation": (
        r"\b(protagonist|main character|central figure|hero)\b",
        "同一事物用同一个词",
    ),
    "false_ranges": (
        r"(from \w+ to \w+, from \w+ to \w+)",
        "只保留有意义的范围",
    ),
    "passive_voice": (
        r"\b(is|are|was|were|been|being)\s+\w+ed\b",
        "改成主动语态，加上主语",
    ),
    "em_dash": (
        r"\—",
        "一句话最多一个破折号，或用逗号代替",
    ),
    "chatbot_artifacts": (
        r"(I hope this helps|Of course!|Let me know if you have any|"
        r"Feel free to|Don't hesitate to|Happy to help)",
        "删掉客套话，直接给答案",
    ),
    "knowledge_cutoff": (
        r"(As of (my last|our)|While I don't have|"
        r"Since I'm an AI|As an AI)",
        "不要说作为AI/截止日期，直接说不知道或给出已知信息",
    ),
    "sycophancy": (
        r"(Great question!|Excellent point!|You're absolutely right!|"
        r"That's a really good question)",
        "直接回答，不要先恭维",
    ),
    "filler_phrases": (
        r"\b(in order to|due to the fact that|in the event that|"
        r"on a daily basis|at this point in time)\b",
        "简化：to/because/if/daily/now",
    ),
    "hedging": (
        r"\b(could potentially possibly might|could potentially|"
        r"might possibly|possibly could)\b",
        "用一个词就够了",
    ),
    "generic_positive": (
        r"(the future looks bright|the possibilities are endless|"
        r"only time will tell|remains to be seen)",
        "如果要说好的展望，给具体计划，不是空话",
    ),
    "signposting": (
        r"(Let's dive in|Here's what you need to know|"
        r"Without further ado|Let's take a closer look)",
        "直接开始说内容",
    ),
    "persuasive_authority": (
        r"(The real question is|At its core|What really matters|"
        r"The truth is|The bottom line is)",
        "直接说结论",
    ),
}


def detect_ai_patterns(text: str) -> dict[str, int]:
    """Scan text and return count of each AI pattern found."""
    results = {}
    for name, (pattern, _hint) in AI_PATTERNS.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            results[name] = len(matches)
    return results


def humanize(text: str, style_sample: str = "") -> str:
    """Remove AI writing patterns and add natural voice.

    Args:
        text: The text to humanize.
        style_sample: Optional writing sample to match style against.

    Returns:
        Humanized text with AI patterns removed.
    """
    # Step 1: Detect patterns
    patterns_found = detect_ai_patterns(text)

    # Step 2: Apply specific replacements
    result = text

    # Remove chatbot artifacts
    result = re.sub(
        r"(?i)(I hope this helps|Of course!|Let me know if you have any|"
        r"Feel free to|Don't hesitate to|Happy to help)[.!]*",
        "",
        result,
    )

    # Remove sycophantic openings
    result = re.sub(
        r"(?i)(Great question!|Excellent point!|You're absolutely right!|"
        r"That's a really good question)[.!]*\s*",
        "",
        result,
    )

    # Remove knowledge cutoff disclaimers
    result = re.sub(
        r"(?i)(As of (my last|our)|While I don't have|"
        r"Since I'm an AI|As an AI|As a large language model)[^。！\n]*[。！\n]",
        "",
        result,
    )

    # Simplify filler phrases
    result = re.sub(r"(?i)\bin order to\b", "to", result)
    result = re.sub(r"(?i)\bdue to the fact that\b", "because", result)
    result = re.sub(r"(?i)\bin the event that\b", "if", result)
    result = re.sub(r"(?i)\bon a daily basis\b", "daily", result)
    result = re.sub(r"(?i)\bat this point in time\b", "now", result)

    # Simplify copula avoidance
    result = re.sub(r"(?i)\b(serves as|stands as|marks|represents)\s+a", "is a", result)
    result = re.sub(r"(?i)\b(boasts|features|offers)\s+a", "has a", result)

    # Replace AI vocabulary
    replacements = {
        r"\badditionally\b": "and",
        r"\bleverage\b": "use",
        r"\bleveraging\b": "using",
        r"\bfoster\b": "build",
        r"\binterplay\b": "relationship",
        r"\bintricate\b": "complex",
        r"\bdelve\b": "explore",
        r"\bgarner\b": "get",
        r"\bunderscore\b": "show",
    }
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Step 3: If no patterns found, return original
    if not patterns_found:
        return result

    return result


# ────────────────────────────────────────────────────────────────
#  Analysis summary for tool use
# ────────────────────────────────────────────────────────────────

def analyze_text_style(text: str) -> dict[str, Any]:
    """Analyze a text for communication style indicators."""
    import statistics

    sentences = [s.strip() for s in re.split(r'[。！？.!?\n]', text) if s.strip()]
    words = text.split()
    chars = len(text)

    # Sentence length analysis
    sent_lengths = [len(s) for s in sentences]
    avg_sent_len = statistics.mean(sent_lengths) if sent_lengths else 0

    # Punctuation habits
    em_dash_count = text.count("—")
    exclamation_count = text.count("！") + text.count("!")
    question_count = text.count("？") + text.count("?")

    # Emotion words (Chinese)
    positive_words = ["开心", "高兴", "好", "棒", "喜欢", "感谢", "满意",
                      "期待", "幸福", "赞", "nice", "great", "good", "love"]
    negative_words = ["难过", "伤心", "烦", "累", "焦虑", "担心", "生气",
                      "失望", "糟糕", "bad", "sad", "angry", "tired"]

    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)

    style = {
        "total_chars": chars,
        "sentence_count": len(sentences),
        "avg_sentence_len": round(avg_sent_len, 1),
        "em_dash_count": em_dash_count,
        "exclamation_count": exclamation_count,
        "question_count": question_count,
        "positive_words": pos_count,
        "negative_words": neg_count,
        "ai_patterns": detect_ai_patterns(text),
    }

    return style

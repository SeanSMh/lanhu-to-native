"""FakeLLMProvider — 测试与 FAKE_LLM=true 场景下使用。

根据 system / user 内容猜出 job_type，返回对应 fixture。
"""

from __future__ import annotations

from typing import Any

# 各 prompt_template_id 的 fixture 响应
FIXTURES: dict[str, dict[str, Any]] = {
    "event_summary": {
        "title": "某公司发布 AI 办公助手",
        "summary": "该产品主打文档协作，发布首日引发行业讨论。",
        "timeline": [
            {"time": "2026-04-23T08:00:00Z", "text": "A 媒体首发"},
            {"time": "2026-04-23T09:15:00Z", "text": "B 公司回应"},
        ],
        "keywords": ["AI办公", "某公司", "生产力"],
        "suggested_angles": [
            {"angle_type": "fact_summary", "label": "事实梳理", "one_liner": "这件事到底发生了什么"},
            {"angle_type": "trend", "label": "趋势解读", "one_liner": "AI 办公未来会怎么走"},
            {"angle_type": "impact_on_people", "label": "普通人影响", "one_liner": "这跟你有什么关系"},
        ],
        "controversy_points": [],
    },
    "angle_generation": {
        "angles": [
            {
                "angle_type": "fact_summary",
                "label": "事实梳理",
                "pitch": "用最短篇幅把这件事讲清楚，避免情绪化",
                "expected_word_count": 800,
            },
            {
                "angle_type": "trend",
                "label": "趋势解读",
                "pitch": "把这件事放进 3 年尺度看，连接到 AI 办公趋势",
                "expected_word_count": 1200,
            },
            {
                "angle_type": "impact_on_people",
                "label": "普通人影响",
                "pitch": "普通白领会不会真的因为这东西换掉 Office",
                "expected_word_count": 1000,
            },
        ]
    },
    "outline_generation": {
        "title_candidates": [
            "AI 办公三年后会变成什么样",
            "别再小看这个 AI 办公产品了",
            "AI 办公的真问题不在功能",
        ],
        "outline": [
            {"section_key": "lead", "title": "导语", "goal": "一句话定调：为什么值得你花 3 分钟看"},
            {"section_key": "background", "title": "背景", "goal": "简述发生了什么、谁做的、在哪发布"},
            {"section_key": "analysis", "title": "核心分析", "goal": "从 3 年尺度看这产品的位置"},
            {"section_key": "impact", "title": "对你影响", "goal": "普通白领会不会真的用它"},
            {"section_key": "ending", "title": "结尾", "goal": "给读者一个判断锚点"},
        ],
    },
    "section_generation": {
        "content_markdown": "## 核心分析\n\n这个产品把 AI 的能力收敛到协作工具里，走了一条和通用助手不同的路。\n\n它赢的前提不是模型有多强，而是能不能在真实文档里沉淀出习惯。",
    },
    "rewrite": {
        "rewritten_text": "改写后的文本（fake）",
    },
    "format_for_toutiao": {
        "formatted_content_markdown": "## 小标题\n\n这是排版后的第一段。\n\n这是排版后的第二段。",
    },
    "image_slot_recommendation": {
        "slots": [
            {"paragraph_index": 0, "suggested_type": "hero", "reason": "导语后主视觉"},
            {"paragraph_index": 1, "suggested_type": "product", "reason": "段落提到产品截图"},
        ]
    },
}


class FakeLLMProvider:
    """根据 system 内容猜 job_type，返回 FIXTURES[job_type]。

    每个 prompt 模板的 SYSTEM 内容都含一些独特关键词，可直接匹配。
    """

    model = "fake-model"

    _MATCHERS = [
        ("event_summary", ["从多条新闻中提炼出核心事件"]),
        ("angle_generation", ["写作选题编辑"]),
        ("outline_generation", ["搭骨架"]),
        ("section_generation", ["代笔某一段"]),
        ("rewrite", ["对给定片段做指定类型的改写"]),
        ("format_for_toutiao", ["排版清洗"]),
        ("image_slot_recommendation", ["图文编辑"]),
    ]

    async def chat_json(self, system: str, user: str, *, timeout_s: float = 25.0) -> dict:
        for job, needles in self._MATCHERS:
            if any(n in system for n in needles):
                return FIXTURES[job]
        # 默认 fallback
        return {"content_markdown": "fake content"}

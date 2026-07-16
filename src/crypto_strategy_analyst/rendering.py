"""JSON and concise Chinese Markdown report rendering."""

from __future__ import annotations

import json

from .models import AnalysisReport


def report_json(report: AnalysisReport) -> str:
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)


def report_markdown(report: AnalysisReport) -> str:
    pattern_names = {
        "double_bottom": "双底",
        "double_top": "双顶",
        "inverse_head_shoulders": "倒头肩底",
        "head_shoulders": "头肩顶",
        "triangle_breakout": "收敛三角突破",
    }
    pattern_states = {"forming": "形成中", "confirmed": "已确认", "invalidated": "已失效"}
    lines = [
        f"# {report.symbol} 盘面分析",
        "",
        "## 当前环境",
        "",
        f"Profile：{report.profile}；市场环境：{report.market['regime']}；综合置信度：{report.confidence:.1f}/100。",
        "",
        "## 关键点位",
        "",
    ]
    for name in ("supports", "resistances"):
        values = report.key_levels[name][:4]
        lines.append(
            f"- {name}："
            + (
                "、".join(
                    f"{item.lower:.8g}–{item.upper:.8g}（强度{item.strength:.0f}）"
                    for item in values
                )
                if values
                else "暂无可靠点位"
            )
        )
    lines += ["", "## 技术指标", ""]
    technical = report.market.get("technical_analysis", {})
    for timeframe, reading in technical.items():
        ema = reading["ema"]
        sma = reading["sma"]
        rsi = reading["rsi"]
        macd = reading["macd"]
        lines.append(
            f"- {timeframe}：偏向 `{reading['bias']}`（一致性{reading['confluence_score']:.0f}/100；"
            f"多/空票 {reading['bullish_votes']}/{reading['bearish_votes']}）；"
            f"EMA {ema['state']}；MA {sma['state']}；RSI({rsi['period']}) "
            f"{rsi['value']:.1f}（{rsi['state']}）；MACD {macd['state']}。"
        )
    if not technical:
        lines.append("K 线不足，无法计算 RSI、MACD、EMA 与 MA。")
    lines += ["", "## 结构形态", ""]
    chart_patterns = report.market.get("chart_patterns", {})
    rendered_patterns = []
    for timeframe, patterns in chart_patterns.items():
        for pattern in patterns:
            rendered_patterns.append(
                f"- {timeframe}：{pattern_names.get(pattern['name'], pattern['name'])}"
                f"（{pattern_states.get(pattern['state'], pattern['state'])}）；"
                f"颈线：{pattern['neckline']:.8g}；失效：{pattern['invalidation']:.8g}。"
            )
    lines += rendered_patterns or ["未发现满足 ATR 尺寸与颈线规则的已确认形态。"]
    lines += ["", "## 接近提醒", ""]
    near_events = [event for event in report.events if event.event_type == "near_key_level"]
    lines += [f"- {event.horizon.value}：{event.payload}" for event in near_events] or [
        "当前未接近高质量关键区域。"
    ]
    labels = {"short": "短线计划", "swing": "波段计划", "long": "长期计划"}
    for horizon, plan in report.horizons.items():
        lines += [
            "",
            f"## {labels[horizon.value]}",
            "",
            f"状态：`{plan.status.value}`；环境：`{plan.market_regime.value}`；策略：`{plan.strategy or '未成立'}`；置信度：{plan.confidence:.1f}。",
        ]
        if plan.entry_range:
            lines.append(
                f"入场范围：{plan.entry_range.lower:.8g}–{plan.entry_range.upper:.8g}；止损：{plan.stop_loss:.8g}；盈亏比：{plan.reward_risk:.2f}R。"
            )
        lines.append(
            "候选条件："
            + (
                "、".join(plan.structure_confirmations + plan.secondary_confirmations)
                or "尚未满足结构确认"
            )
        )
        lines.append("失效条件：" + ("、".join(plan.invalidation_conditions) or "等待策略成立"))
    missing = [
        name
        for name, point in report.data_availability.items()
        if point.status.value != "available"
    ]
    lines += [
        "",
        "## 缺失数据",
        "",
        "、".join(missing) if missing else "无关键数据缺失。",
        "",
        "## 风险说明",
        "",
        "仅供策略研究，不保证收益，不构成投资建议。OpenClaw负责编排、去重和通知，本Skill不发送消息。",
    ]
    return "\n".join(lines)

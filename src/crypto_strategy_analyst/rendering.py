"""JSON and concise Chinese Markdown rendering."""

from __future__ import annotations

import json

from .models import AnalysisReport


def report_json(report: AnalysisReport) -> str:
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)


def report_markdown(report: AnalysisReport) -> str:
    lines = [
        f"# {report.market['symbol']} 策略分析",
        "",
        f"- Profile：{report.profile}",
        f"- 价格：{report.market['price']}",
        f"- 置信度：{report.confidence:.1f}/100",
        "",
        "## 分周期计划",
        "",
    ]
    for horizon, plan in report.plans.items():
        lines += [
            f"### {horizon.value}",
            "",
            f"状态：`{plan.status.value}`；策略：`{plan.strategy}`；仓位上限：{plan.position_fraction:.1%}",
            f"入场/止损/TP1/TP2：{plan.entry} / {plan.stop} / {plan.take_profit_1} / {plan.take_profit_2}",
            "",
        ]
    if report.warnings:
        lines += ["## 警告", "", *[f"- {item}" for item in report.warnings], ""]
    lines += ["研究用途，不构成投资建议，也不保证收益。"]
    return "\n".join(lines)

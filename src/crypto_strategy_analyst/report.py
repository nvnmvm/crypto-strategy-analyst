"""JSON and Chinese Markdown report rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import AnalysisReport, BacktestResult, PriceZone


def _value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.4f}"
    return str(value)


def _zone_lines(zones: list[PriceZone]) -> str:
    if not zones:
        return "- 暂无可信区域"
    return "\n".join(
        f"- {zone.lower_price:,.4f}–{zone.upper_price:,.4f}（中心 {zone.center_price:,.4f}，"
        f"强度 {zone.strength_score:.1f}，独立触碰 {zone.touch_count} 次，"
        f"反弹 {zone.reaction_count} 次，跌破/突破 {zone.break_count} 次，周期 {zone.timeframe}）"
        for zone in zones
    )


def analysis_markdown(report: AnalysisReport) -> str:
    """Render the required human-readable Chinese analysis."""

    position = report.suggested_position_size
    if position == "not_available":
        position_text = "不可用（当前没有通过硬性规则的候选）"
    else:
        position_text = (
            f"数量 {position.quantity:.8f}，投入约 ¥{position.position_notional_cny:.2f}，"
            f"止损风险约 ¥{position.risk_amount_cny:.2f}"
        )
    quality_lines = "\n".join(
        f"- {timeframe}: {quality.grade.value}，{quality.bars} 根，gap={quality.gap_count}"
        for timeframe, quality in report.data_quality.items()
    )
    missing = "、".join(f"{key}={value}" for key, value in report.missing_data.items())
    warnings = "\n".join(f"- {item}" for item in report.warnings) or "- 无额外警告"
    invalidations = "\n".join(f"- {item}" for item in report.invalidation_conditions)
    score = report.score_breakdown
    return (
        f"""# {report.symbol} 现货策略研究报告

- 生成时间（UTC）：{report.generated_at.isoformat()}
- 数据来源：{report.data_source}
- 市场：Binance 现货
- 当前价格：{report.current_price:,.4f} USDT

## 1. 当前结论

**{report.signal.value}**，确定性评分 **{report.signal_score:.1f}/100**。

## 2. 日线趋势

{report.daily_trend.value}

## 3. 4 小时交易结构

{report.four_hour_trend.value}

## 4. 1 小时确认情况

{report.one_hour_confirmation}

## 5. 关键支撑区域

{_zone_lines(report.support_zones)}

## 6. 关键阻力区域

{_zone_lines(report.resistance_zones)}

## 7. 技术指标

| 周期 | EMA20 | EMA50 | EMA200 | RSI14 | MACD柱 | ATR14 | ADX14 | 量比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
"""
        + "\n".join(
            f"| {tf} | {item.ema20:.4f} | {item.ema50:.4f} | {item.ema200:.4f} | "
            f"{item.rsi14:.2f} | {item.macd_histogram:.4f} | {item.atr14:.4f} | "
            f"{_value(item.adx14)} | {item.volume_ratio:.2f} |"
            for tf, item in report.indicators.items()
        )
        + f"""

## 8. 信号评分和明细

- 大周期趋势：{score.higher_timeframe_trend:.1f}/20
- 支撑阻力：{score.support_resistance:.1f}/25
- K 线确认：{score.candlestick_confirmation:.1f}/15
- 成交量确认：{score.volume_confirmation:.1f}/15
- 技术指标：{score.indicator_confirmation:.1f}/15
- 盈亏比与空间：{score.reward_risk_space:.1f}/10
- 新闻情绪调整：{score.sentiment_adjustment:.1f}（当前未接入）

## 9. 建议入场区域

{_value(report.entry_zone)}

## 10. 止损

{_value(report.stop_loss)}

## 11. 分批止盈

- 第一目标（建议减 30%）：{_value(report.take_profit_1)}
- 第二目标（建议再减 30%）：{_value(report.take_profit_2)}
- 余下 40%：{report.trailing_stop_method} 移动止损

## 12. 仓位建议

{position_text}

## 13. 最大可能亏损

{_value(report.maximum_loss_amount)} CNY；该数值与投入金额不同。

## 14. 不交易的条件

{invalidations}

## 15. 数据质量、缺失和风险警告

{quality_lines}

缺失数据：{missing}

{warnings}

> {report.disclaimer}
"""
    )


def save_analysis(report: AnalysisReport, output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    symbol = report.symbol.replace("/", "-")
    json_path = directory / f"{symbol}-{stamp}.json"
    markdown_path = directory / f"{symbol}-{stamp}.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    markdown_path.write_text(analysis_markdown(report), encoding="utf-8")
    (directory / f"latest-{symbol}.json").write_text(
        json_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (directory / f"latest-{symbol}.md").write_text(
        markdown_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return json_path, markdown_path


def save_backtest(result: BacktestResult, output_dir: str | Path) -> Path:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    symbol = result.symbol.replace("/", "-")
    path = directory / f"backtest-{symbol}-{stamp}.json"
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return path


def find_latest(output_dir: str | Path, symbol: str | None = None) -> Path:
    directory = Path(output_dir).expanduser().resolve()
    pattern = f"latest-{symbol.replace('/', '-')}.md" if symbol else "latest-*.md"
    files = sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no saved report in {directory}")
    return files[0]

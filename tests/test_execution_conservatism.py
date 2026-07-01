from __future__ import annotations

from crypto_strategy_analyst.backtest import conservative_buy_fill, conservative_sell_fill


def test_market_fill_rounding_is_never_favorable(trading_rules):
    rules = trading_rules.model_copy(update={"price_tick_size": 0.1})
    buy = conservative_buy_fill(100.01, 0.0005, rules)
    sell = conservative_sell_fill(100.01, 0.0005, rules)
    assert buy >= 100.01 * 1.0005
    assert sell <= 100.01 * 0.9995

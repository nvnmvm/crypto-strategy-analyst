"""Exchange-shaped wrapper over the local paper broker."""

from __future__ import annotations

from ..portfolio import PaperBroker


class PaperExchange:
    def __init__(self, broker: PaperBroker):
        self.broker = broker

    def place(self, symbol: str, side: str, quantity: float, price: float):
        return self.broker.execute(symbol, side.lower(), quantity, price)

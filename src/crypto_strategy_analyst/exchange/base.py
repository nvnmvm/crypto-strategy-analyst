"""Generic exchange adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OrderDraft, OrderResult


class ExchangeAdapter(ABC):
    @abstractmethod
    def ticker(self, symbol: str) -> float: ...

    @abstractmethod
    def create_draft(
        self, symbol: str, side: str, quantity: float, reference_price: float
    ) -> tuple[OrderDraft, str]: ...

    @abstractmethod
    def place_spot_order(self, draft: OrderDraft, confirmation_token: str) -> OrderResult: ...

    @abstractmethod
    def query_order(self, symbol: str, client_order_id: str) -> OrderResult | None: ...

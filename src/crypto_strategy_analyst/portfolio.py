"""Paper-only account state and trade recording."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .models import PaperAccount
from .storage import append_jsonl, atomic_json_write, file_lock, read_json


class PaperBroker:
    def __init__(self, account_path: str | Path, trades_path: str | Path):
        self.account_path = Path(account_path)
        self.trades_path = Path(trades_path)
        self.lock_path = self.account_path.with_suffix(".lock")

    def load(self) -> PaperAccount:
        return PaperAccount.model_validate(
            read_json(self.account_path, PaperAccount().model_dump(mode="json"))
        )

    def execute(
        self, symbol: str, side: str, quantity: float, price: float, fee_rate: float = 0.001
    ) -> PaperAccount:
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        with file_lock(self.lock_path):
            account = self.load()
            notional = quantity * price
            fee = notional * fee_rate
            positions = dict(account.positions)
            if side == "buy":
                if notional + fee > account.cash:
                    raise ValueError("insufficient paper cash")
                account.cash -= notional + fee
                positions[symbol] = positions.get(symbol, 0) + quantity
            elif side == "sell":
                if positions.get(symbol, 0) < quantity:
                    raise ValueError("insufficient paper position")
                account.cash += notional - fee
                positions[symbol] -= quantity
            else:
                raise ValueError("side must be buy or sell")
            account.positions = positions
            account.updated_at = datetime.now(UTC)
            atomic_json_write(self.account_path, account.model_dump(mode="json"))
            append_jsonl(
                self.trades_path,
                {
                    "at": account.updated_at.isoformat(),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "fee": fee,
                },
            )
            return account

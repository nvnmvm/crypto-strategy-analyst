from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _production_text() -> str:
    paths = [*ROOT.glob("src/**/*.py"), *ROOT.glob("scripts/*.py")]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_no_real_order_calls_exist():
    text = _production_text()
    forbidden = re.compile(
        r"\.(create_order|place_order|submit_order|futures_create_order|create_margin_order)\s*\("
    )
    assert not forbidden.search(text)


def test_no_private_trading_or_leverage_endpoints_exist():
    text = _production_text()
    forbidden = [
        r"/api/v3/(order|account|myTrades)",
        r"/fapi/",
        r"/dapi/",
        r"X-MBX-APIKEY",
        r"\.set_leverage\s*\(",
    ]
    assert not any(re.search(pattern, text) for pattern in forbidden)


def test_no_hardcoded_secret_patterns_exist():
    text = _production_text()
    patterns = [
        r"(?i)(api[_-]?key|secret[_-]?key)\s*=\s*['\"][A-Za-z0-9]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
    ]
    assert not any(re.search(pattern, text) for pattern in patterns)


def test_no_hardcoded_user_paths_in_runtime_code():
    text = _production_text()
    assert "/Users/" not in text
    assert "C:\\Users\\" not in text

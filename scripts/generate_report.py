#!/usr/bin/env python3
from __future__ import annotations

import sys

from crypto_strategy_analyst.cli import main

arguments = [item for item in sys.argv[1:] if item != "--latest"]
raise SystemExit(main(["latest", *arguments]))

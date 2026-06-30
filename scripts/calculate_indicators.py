#!/usr/bin/env python3
from __future__ import annotations

import sys

from crypto_strategy_analyst.cli import main

raise SystemExit(main(["indicators", *sys.argv[1:]]))

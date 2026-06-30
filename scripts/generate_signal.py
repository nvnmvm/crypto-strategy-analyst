#!/usr/bin/env python3
from __future__ import annotations

import sys

from crypto_strategy_analyst.cli import main

# Signal generation always runs the complete data-quality and risk pipeline.
raise SystemExit(main(["analyze", *sys.argv[1:]]))

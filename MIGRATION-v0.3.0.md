# Migration to v0.3.0

v0.3.0 converts the project into an analysis-only OpenClaw Skill and replaces the simplified v0.2.0 strategy placeholders.

## Removed

- Top-level `exchange`, `portfolio`, and `journal` commands.
- Exchange adapter package, paper portfolio, manual journal and state storage modules.
- All account, credential, order, confirmation-token, testnet and paper-position configuration.
- The temporary v0.1.x `risk` compatibility path.

## Added

- Seven public market regimes and six independently evaluated strategies.
- Structural and secondary confirmation separation, multi-source price zones and near-level events.
- Dedicated behavioral methods for BTC, ETH, BNB and SOL Profiles plus constrained Generic analysis.
- Public funding, open-interest, relative-pair and BTC-dominance sources; external JSON injection for unavailable contexts.
- Immutable next-bar entry validation, strict OHLC replay, fixed-date splits and real research diagnostics.
- Schema 3.0 reports and stable OpenClaw event deduplication keys.

## Baseline

The v0.2.0 `main` and tag resolve to `865c7ec7863285220c6b24957f8410a52685fa5c`. It contained 1,697 production Python lines, 25 modules, 45 tests, 9 top-level commands, 39 configuration fields, and a 40,082-byte wheel. Final v0.3.0 measurements are recorded after build verification.

The verified v0.3.0 candidate contains 3,481 production Python lines, 41 deliberately separated modules, 59 tests, 6 top-level commands (13 including research subcommands), 53 configuration fields, and an approximately 63.4 KB wheel. The increases—105.1% in production lines, 64.0% in modules and 35.9% in configuration fields—replace v0.2.0 placeholders with independent strategies, data adapters, validation, replay and research behavior. Top-level commands fell by three and all execution/account surfaces were removed. The exact final wheel byte size is reported after the last build because embedding that number changes the archive itself.

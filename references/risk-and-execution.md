# Risk and execution

Paper accounting is the default. The paper account is stored in `state/paper-account.json` and trades in `state/paper-trades.jsonl`. Writes use an exclusive lock, temporary file, flush/fsync, atomic replacement and backup recovery.

Real Binance Spot execution is opt-in. Safe defaults are `trading_enabled: false`, `futures_enabled: false`, `require_human_confirmation: true`, and `testnet: true`. Secrets are loaded only from named environment variables.

Every order follows candidate → validate entry → create draft → show draft → explicit human confirmation → place → query status → record. The adapter checks symbol whitelist, expiration, confirmation digest, maximum notional, position fraction, price deviation, emergency stop and client order ID. It queries before submission to prevent duplicates. A network timeout triggers status lookup and never a blind order retry.

There are deliberately no margin, futures, leverage, borrowing, short-selling, withdrawal, transfer, or API-key management methods.

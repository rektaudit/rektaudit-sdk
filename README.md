# rektaudit-sdk

Official Python SDK for [RektAudit](https://github.com/rektaudit/rektaudit) — sign and submit decision + outcome events to a certified ledger.

## Requirements

- Python 3.10+
- A RektAudit API key (`ra_…`) from your dashboard
- Your organization UUID

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "git+https://github.com/rektaudit/rektaudit-sdk.git"
```

Pin a tag when releases are published:

```bash
pip install "git+https://github.com/rektaudit/rektaudit-sdk.git@v0.1.0"
```

Local development checkout:

```bash
git clone https://github.com/rektaudit/rektaudit-sdk.git
cd rektaudit-sdk
pip install -e .
```

## Quick example

```python
from datetime import datetime, timezone

from rektaudit import RektauditClient

API_KEY = "ra_YOUR_API_KEY"
BASE_URL = "https://your-rektaudit-instance.example.com"
ORGANIZATION_ID = "your-org-uuid"

keys = RektauditClient.generate_keypair()
client = RektauditClient(
    private_key_b64=keys["private_key"],
    base_url=BASE_URL,
    debug=True,
)
client.session.headers["X-API-Key"] = API_KEY

client.register_or_get_agent(ORGANIZATION_ID, "my-agent")
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

decision = client.submit_decision(
    organization_id=ORGANIZATION_ID,
    context_json={"rsi": 28, "market_regime": "trend"},
    public_decision="Enter BTC long — RSI oversold",
    public_context="BTC 4h RSI=28, vol +18% vs 7d avg",
    ts=ts,
)

outcome = client.submit_outcome(
    organization_id=ORGANIZATION_ID,
    decision_event_hash=decision["event_hash"],
    outcome_type="pnl",
    outcome_value=1.0,
    ts=ts,
)

print("Decision proof:", f"{BASE_URL}/e/{decision['event_hash']}")
print("Outcome proof:", f"{BASE_URL}/e/{outcome['event_hash']}")
```

## API surface

- `RektauditClient.generate_keypair()` — Ed25519 keypair for signing
- `register_or_get_agent(organization_id, name)` — register agent public key
- `submit_decision(...)` / `submit_outcome(...)` — convenience wrappers
- `submit_event(payload)` — low-level signed `POST /events`

Billing note: API-key submissions are billable on hosted RektAudit instances. Dashboard test events are not submitted through this SDK path.

## License

MIT — see [LICENSE](LICENSE).
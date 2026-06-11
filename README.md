# rektaudit-sdk

Official Python SDK for [RektAudit](https://github.com/rektaudit/rektaudit) — sign and submit decision + outcome events to a certified ledger.

## Requirements

- Python 3.10+
- A RektAudit API key (`ra_…`) from your dashboard

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "git+https://github.com/rektaudit/rektaudit-sdk.git"
```

Pin a tag when releases are published:

```bash
pip install "git+https://github.com/rektaudit/rektaudit-sdk.git@v0.1.1"
```

Local development checkout:

```bash
git clone https://github.com/rektaudit/rektaudit-sdk.git
cd rektaudit-sdk
pip install -e .
```

## Quick example (recommended)

Attach your API key once, resolve your organization, then submit events without repeating `organization_id`:

```python
from datetime import datetime, timezone

from rektaudit import RektauditClient

API_KEY = "ra_YOUR_API_KEY"
BASE_URL = "https://your-rektaudit-instance.example.com"

keys = RektauditClient.generate_keypair()
client = RektauditClient(
    private_key_b64=keys["private_key"],
    base_url=BASE_URL,
    api_key=API_KEY,
    debug=True,
)

org = client.get_or_create_org()  # cached; sets default_organization_id
client.default_organization_id = org["id"]  # optional — already set by get_or_create_org()

client.register_or_get_agent("my-agent")
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

decision = client.submit_decision(
    context_json={"rsi": 28, "market_regime": "trend"},
    public_decision="Enter BTC long — RSI oversold",
    public_context="BTC 4h RSI=28, vol +18% vs 7d avg",
    ts=ts,
)

outcome = client.submit_outcome(
    decision_event_hash=decision["event_hash"],
    outcome_type="pnl",
    outcome_value=1.0,
    ts=ts,
)

print("Decision proof:", f"{BASE_URL}/e/{decision['event_hash']}")
print("Outcome proof:", f"{BASE_URL}/e/{outcome['event_hash']}")
```

## Explicit mode (advanced)

Pass `organization_id` on each call, or set `default_organization_id` in the constructor:

```python
client = RektauditClient(
    private_key_b64=keys["private_key"],
    base_url=BASE_URL,
    api_key=API_KEY,
    default_organization_id="your-org-uuid",
)

client.register_or_get_agent("my-agent", organization_id="your-org-uuid")
decision = client.submit_decision(
    organization_id="your-org-uuid",
    context_json={"rsi": 28},
    ts=ts,
)
```

## API surface

- `RektauditClient.generate_keypair()` — Ed25519 keypair for signing
- `get_or_create_org()` — resolve org via API key or signing public key (cached)
- `register_or_get_agent(name, organization_id=None)` — register agent public key
- `submit_decision(...)` / `submit_outcome(...)` — convenience wrappers (`organization_id` optional when default is set)
- `submit_event(payload)` — low-level signed `POST /events`

Billing note: API-key submissions are billable on hosted RektAudit instances. Dashboard test events are not submitted through this SDK path.

## License

MIT — see [LICENSE](LICENSE).
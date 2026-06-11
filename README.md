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
pip install "git+https://github.com/rektaudit/rektaudit-sdk.git@v0.1.2"
```

Local development checkout:

```bash
git clone https://github.com/rektaudit/rektaudit-sdk.git
cd rektaudit-sdk
pip install -e .
```

## Quick example (recommended)

Pass your API key — org and agent setup happen automatically:

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
)

ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
decision = client.submit_decision(
    context_json={"rsi": 28, "market_regime": "trend"},
    public_decision="Enter BTC long — RSI oversold",
    ts=ts,
)
outcome = client.submit_outcome(
    decision_event_hash=decision["event_hash"],
    outcome_type="pnl",
    outcome_value=1.0,
    ts=ts,
)
```

On first submit, the SDK auto-registers a `default-agent` (logged when `debug=True`). Call `client.ensure_agent("my-bot")` to pick a name upfront.

## Explicit mode (advanced)

```python
client = RektauditClient(
    private_key_b64=keys["private_key"],
    base_url=BASE_URL,
    default_organization_id="your-org-uuid",
)
client.ensure_agent("my-agent", organization_id="your-org-uuid")
decision = client.submit_decision(
    organization_id="your-org-uuid",
    context_json={"rsi": 28},
    ts=ts,
)
```

Manual setup still works: `get_or_create_org()` and `register_or_get_agent(name)`.

## API surface

- `RektauditClient.generate_keypair()` — Ed25519 keypair for signing
- `get_or_create_org()` — resolve org via API key or signing public key (cached; auto-called when `api_key` is set)
- `ensure_agent(name="default-agent")` — register agent if needed
- `register_or_get_agent(name, organization_id=None)` — explicit agent registration
- `submit_decision(...)` / `submit_outcome(...)` — auto-register agent on first use
- `submit_event(payload)` — low-level signed `POST /events`

Billing note: API-key submissions are billable on hosted RektAudit instances. Dashboard test events are not submitted through this SDK path.

## License

MIT — see [LICENSE](LICENSE).
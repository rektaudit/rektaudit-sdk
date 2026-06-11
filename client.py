import time
import json
import requests
from nacl.signing import SigningKey
import base64
import os


class Client:

    @staticmethod
    def save_private_key(path: str, private_key_b64: str):
        with open(path, "w") as f:
            f.write(private_key_b64)

    @staticmethod
    def generate_keypair():
        signing_key = SigningKey.generate()
        verify_key = signing_key.verify_key

        private_key_b64 = base64.b64encode(signing_key.encode()).decode()
        public_key_b64 = base64.b64encode(verify_key.encode()).decode()

        return private_key_b64, public_key_b64

    def _sync_state(self):
        try:
            response = requests.get(
                f"{self.base_url}/agent/state/{self.public_key}",
                timeout=5,
            )

            # Agent not registered
            if response.status_code == 404:
                if not self.allow_unregistered:
                    raise RuntimeError(
                        f"Agent not registered at {self.base_url}"
                    )

                if self.initial_equity is None:
                    raise RuntimeError(
                        "Agent not registered and no initial_equity provided."
                    )

                self._current_equity = float(self.initial_equity)
                return

            response.raise_for_status()

        except requests.RequestException as e:
            raise RuntimeError(
                f"Failed to connect to RektAudit at {self.base_url}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise RuntimeError(
                "Invalid JSON received from RektAudit"
            ) from e

        current_equity = data.get("current_equity")

        if current_equity is None:
            # Registered agent but no equity recorded yet
            if self.initial_equity is None:
                raise RuntimeError(
                    "Agent has no starting equity. Provide initial_equity when constructing Client."
                )
            self._current_equity = float(self.initial_equity)
        else:
            # Normal case: trust server as source of truth
            self._current_equity = float(current_equity)

    def __init__(
        self,
        private_key: str,
        base_url: str | None = None,
        initial_equity: float | None = None,
        allow_unregistered: bool = False,
    ):
        resolved_base_url = base_url or os.getenv(
            "REKTAUDIT_BASE_URL",
            "http://localhost:8000"
        )

        self.base_url = resolved_base_url.rstrip("/")
        self.initial_equity = initial_equity
        self.allow_unregistered = allow_unregistered

        self.signing_key = SigningKey(base64.b64decode(private_key))
        self.public_key = base64.b64encode(
            self.signing_key.verify_key.encode()
        ).decode()

        self._sync_state()

    def register_agent(
        self,
        name: str,
        declared_max_risk: float,
        declared_leverage_limit: float,
    ):
        payload = {
            "name": name,
            "public_key": self.public_key,
            "declared_max_risk": declared_max_risk,
            "declared_leverage_limit": declared_leverage_limit,
        }

        response = requests.post(
            f"{self.base_url}/agents",
            json=payload,
            timeout=5,
        )

        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(
                f"Failed to register agent: {response.text}"
            ) from e

        return response.json()

    def submit_trade(
        self,
        *,
        equity_before: float,
        equity_after: float,
        trade_id: int,
        timestamp: int | None = None,
    ):
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        payload = {
            "public_key": self.public_key,
            "trade_id": trade_id,
            "timestamp": timestamp,
            "equity_before": equity_before,
            "equity_after": equity_after,
        }

        body = json.dumps(payload).encode()

        signature_b64 = base64.b64encode(
            self.signing_key.sign(body).signature
        ).decode()

        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature_b64,
        }

        response = requests.post(
            f"{self.base_url}/trades",
            data=body,
            headers=headers,
            timeout=10,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.ok:
            self._current_equity = equity_after
        else:
            self._sync_state()

        return {
            "status_code": response.status_code,
            "ok": response.ok,
            "data": data,
        }

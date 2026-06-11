__version__ = "0.1.0"

import base64
import json
import time
from typing import Any, Dict, Optional

import requests
from nacl.signing import SigningKey
from requests.adapters import HTTPAdapter


def _stable_json(obj):
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class RektauditError(Exception):
    def __init__(self, code: str, message: str, status_code: int = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class RektauditClient:
    """
    Minimal, correct SDK for RektAudit event ingestion.

    Responsibilities:
    - sign payloads
    - submit events
    - retry when appropriate
    - log what it's doing (debug visibility)
    """

    RETRYABLE_CODES = {
        "DECISION_NOT_COMMITTED_YET",
    }

    def __init__(
        self,
        private_key_b64: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
        debug: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.debug = debug

        self.signing_key = SigningKey(base64.b64decode(private_key_b64))
        self.public_key = base64.b64encode(
            self.signing_key.verify_key.encode()
        ).decode()

        self._agent_id_cache = None

        self.session = requests.Session()
        self.session.headers.update({
            "Connection": "close"
        })

        if False:
            self.session = requests.Session()

            adapter = HTTPAdapter(
                pool_connections=24,
                pool_maxsize=24,
            )

            self.session.mount(
                "http://",
                adapter,
            )

        print(
            f"[SDK] base_url={self.base_url}",
            flush=True,
        )

    def _log(self, msg: str):
        if self.debug:
            print(f"[SDK] {msg}", flush=True)

    @staticmethod
    def generate_keypair():
        signing_key = SigningKey.generate()
        verify_key = signing_key.verify_key

        return {
            "private_key": base64.b64encode(signing_key.encode()).decode(),
            "public_key": base64.b64encode(verify_key.encode()).decode(),
        }

    def _serialize(self, payload: dict) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def _sign(self, body: bytes) -> str:
        return base64.b64encode(
            self.signing_key.sign(body).signature
        ).decode()

    def _post(self, path: str, payload: dict) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"

        body = self._serialize(payload)

        headers = {
            "Content-Type": "application/json",
            "X-Signature": self._sign(body),
        }

        self._log(f"POST {path}")

        resp = self.session.post(
            url,
            data=body,
            headers=headers,
            timeout=self.timeout,
        )
        try:
            data = resp.json()
        except Exception:
            raise RektauditError(
                code="INVALID_RESPONSE",
                message=resp.text,
                status_code=resp.status_code,
            )

        if resp.ok:
            return data

        detail = data.get("detail", {})

        if isinstance(detail, dict):
            code = detail.get("code", "UNKNOWN_ERROR")
            message = detail.get("message", str(detail))
        else:
            code = str(detail)
            message = str(detail)

        self._log(f"ERROR {code}: {message}")

        raise RektauditError(code, message, resp.status_code)

    def get_or_create_org(self):
        resp = self.session.get(f"{self.base_url}/org/by-public-key/{self.public_key}", timeout=5)

        if resp.status_code == 200:
            return resp.json()["organization_id"]

        payload = {
            "name": "SDK Org",
            "owner_public_key": self.public_key
        }

        resp = self.session.post(
            f"{self.base_url}/org/",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["organization_id"]

    def register_or_get_agent(
        self,
        organization_id: str,
        name: str,
        declared_max_risk: float = 1.0,
        declared_leverage_limit: float = 1.0,
    ):
        if self._agent_id_cache:
            return self._agent_id_cache

        payload = {
            "organization_id": organization_id,
            "name": name,
            "public_key": self.public_key,
            "declared_max_risk": declared_max_risk,
            "declared_leverage_limit": declared_leverage_limit,
        }

        try:
            resp = self.session.post(
                f"{self.base_url}/agents",
                json=payload,
                timeout=5,
            )

            if resp.status_code == 200:
                agent_id = resp.json()["id"]
                self._agent_id_cache = agent_id
                return agent_id

        except Exception:
            pass

        resp = self.session.get(f"{self.base_url}/agents", timeout=5)
        resp.raise_for_status()

        agents = resp.json().get("agents", [])

        for a in agents:
            if a["public_key"] == self.public_key:
                self._agent_id_cache = a["id"]
                return a["id"]

        raise RuntimeError("Agent create + lookup failed")

    def submit_event(
        self,
        payload: dict,
        *,
        retry: bool = True,
        max_retries: int = 5,
        backoff_start: float = 0.05,
        backoff_max: float = 1.0,
    ) -> Dict[str, Any]:

        payload = dict(payload)
        payload["agent_public_key"] = self.public_key

        attempt = 0
        backoff = backoff_start

        while True:
            attempt += 1

            try:
                result = self._post("/events", payload)
                return result

            except RektauditError as e:

                if (
                    retry
                    and e.code in self.RETRYABLE_CODES
                    and attempt < max_retries
                ):
                    print(
                        f"[RETRY] attempt={attempt} code={e.code} "
                        f"sleep={backoff:.3f}s",
                        flush=True,
                    )

                    time.sleep(backoff)
                    backoff = min(backoff * 2, backoff_max)
                    continue

                raise

    def submit_decision(
        self,
        *,
        organization_id: str,
        scenario_hash: Optional[str] = None,
        context_json: Optional[dict] = None,
        ts: Optional[str] = None,
        metadata_json: Optional[dict] = None,
        **kwargs,
    ):
        payload = {
            "organization_id": organization_id,
            "event_type": "decision",
            "scenario_hash": scenario_hash,
            "context_json": context_json,
            "ts": ts,
            "metadata_json": metadata_json,
        }
        payload.update(kwargs)

        return self.submit_event(payload)

    def submit_outcome(
        self,
        *,
        organization_id: str,
        decision_event_hash: str,
        outcome_type: str,
        outcome_value: float,
        ts: Optional[str] = None,
        metadata_json: Optional[dict] = None,
        retry: bool = True,
        **kwargs,
    ):
        payload = {
            "organization_id": organization_id,
            "event_type": "outcome",
            "decision_event_hash": decision_event_hash,
            "outcome_type": outcome_type,
            "outcome_value": outcome_value,
        }

        if ts is not None:
            payload["ts"] = ts

        if metadata_json is not None:
            payload["metadata_json"] = metadata_json

        payload.update(kwargs)

        return self.submit_event(payload, retry=retry)
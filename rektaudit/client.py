__version__ = "0.1.3"

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

    DEFAULT_AGENT_NAME = "default-agent"

    def __init__(
        self,
        private_key_b64: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
        debug: bool = True,
        api_key: str | None = None,
        default_organization_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.debug = debug
        self.default_organization_id = default_organization_id

        self.signing_key = SigningKey(base64.b64decode(private_key_b64))
        self.public_key = base64.b64encode(
            self.signing_key.verify_key.encode()
        ).decode()

        self._agent_id_cache = None
        self._org_cache: Dict[str, str] | None = None

        self.session = requests.Session()
        self.session.headers.update({
            "Connection": "close"
        })

        if api_key:
            self.session.headers["X-API-Key"] = api_key
            if not self.default_organization_id:
                self._resolve_org_from_api_key()

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

    def _resolve_organization_id(self, organization_id: str | None) -> str:

        resolved = organization_id or self.default_organization_id
        if not resolved:
            raise RektauditError(
                "ORGANIZATION_ID_REQUIRED",
                "Pass organization_id or set default_organization_id (e.g. via get_or_create_org()).",
            )
        return resolved

    def _cache_org(self, org_id: str, *, name: str | None = None) -> Dict[str, str]:

        org = {
            "id": org_id,
            "organization_id": org_id,
        }
        if name:
            org["name"] = name
        self._org_cache = org
        if not self.default_organization_id:
            self.default_organization_id = org_id
        return org

    def _org_resolution_hint(self) -> str:
        return (
            "Pass default_organization_id=... in RektauditClient(...) "
            "(your dashboard quickstart includes this UUID)."
        )

    def _resolve_org_from_api_key(self) -> Dict[str, str]:

        if not self.session.headers.get("X-API-Key"):
            raise RektauditError(
                "API_KEY_REQUIRED",
                f"No API key configured. {self._org_resolution_hint()}",
            )

        url = f"{self.base_url}/auth/api-key/context"

        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RektauditError(
                "ORG_RESOLUTION_FAILED",
                f"Could not reach {url}: {exc}. {self._org_resolution_hint()}",
            )

        if resp.status_code != 200:
            code = "ORG_RESOLUTION_FAILED"
            message = resp.text
            try:
                data = resp.json()
                detail = data.get("detail", data)
                if isinstance(detail, dict):
                    code = detail.get("code", code)
                    message = detail.get("message", str(detail))
                else:
                    message = str(detail)
            except Exception:
                message = f"HTTP {resp.status_code}"

            raise RektauditError(
                code,
                f"{message} {self._org_resolution_hint()}",
                resp.status_code,
            )

        data = resp.json()
        org_id = data.get("id") or data.get("organization_id")
        if not org_id:
            raise RektauditError(
                "ORG_RESOLUTION_FAILED",
                f"API key context missing organization id. {self._org_resolution_hint()}",
                resp.status_code,
            )

        org = self._cache_org(str(org_id), name=data.get("name"))
        self.default_organization_id = str(org_id)
        self._log(f"Resolved organization {org_id} from API key")
        return org

    def get_or_create_org(self) -> Dict[str, str]:

        if self._org_cache:
            return self._org_cache

        if self.session.headers.get("X-API-Key"):
            return self._resolve_org_from_api_key()

        resp = self.session.get(
            f"{self.base_url}/org/by-public-key/{self.public_key}",
            timeout=self.timeout,
        )

        if resp.status_code == 200:
            data = resp.json()
            org_id = data.get("organization_id") or data.get("id")
            if org_id:
                return self._cache_org(str(org_id), name=data.get("name"))

        payload = {
            "name": "SDK Org",
            "owner_public_key": self.public_key,
        }

        resp = self.session.post(
            f"{self.base_url}/org/",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        org_id = data.get("organization_id") or data.get("id")
        return self._cache_org(str(org_id))

    def register_or_get_agent(
        self,
        name: str,
        organization_id: str | None = None,
        declared_max_risk: float = 1.0,
        declared_leverage_limit: float = 1.0,
    ):
        if self._agent_id_cache:
            return self._agent_id_cache

        org_id = self._resolve_organization_id(organization_id)

        payload = {
            "organization_id": org_id,
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

    def ensure_agent(
        self,
        name: str = DEFAULT_AGENT_NAME,
        organization_id: str | None = None,
        declared_max_risk: float = 1.0,
        declared_leverage_limit: float = 1.0,
    ) -> str:

        if self._agent_id_cache:
            return self._agent_id_cache

        return self.register_or_get_agent(
            name,
            organization_id=organization_id,
            declared_max_risk=declared_max_risk,
            declared_leverage_limit=declared_leverage_limit,
        )

    def _ensure_agent_for_submit(self, agent_name: str = DEFAULT_AGENT_NAME) -> None:

        if self._agent_id_cache:
            return

        self._log(
            f"No agent registered; auto-registering '{agent_name}' "
            "(call ensure_agent() to choose a name)"
        )
        self.ensure_agent(agent_name)

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
        organization_id: str | None = None,
        scenario_hash: Optional[str] = None,
        context_json: Optional[dict] = None,
        ts: Optional[str] = None,
        metadata_json: Optional[dict] = None,
        **kwargs,
    ):
        payload = {
            "organization_id": self._resolve_organization_id(organization_id),
            "event_type": "decision",
            "scenario_hash": scenario_hash,
            "context_json": context_json,
            "ts": ts,
            "metadata_json": metadata_json,
        }
        payload.update(kwargs)

        self._ensure_agent_for_submit()
        return self.submit_event(payload)

    def submit_outcome(
        self,
        *,
        organization_id: str | None = None,
        decision_event_hash: str,
        outcome_type: str,
        outcome_value: float,
        ts: Optional[str] = None,
        metadata_json: Optional[dict] = None,
        retry: bool = True,
        **kwargs,
    ):
        payload = {
            "organization_id": self._resolve_organization_id(organization_id),
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

        self._ensure_agent_for_submit()
        return self.submit_event(payload, retry=retry)
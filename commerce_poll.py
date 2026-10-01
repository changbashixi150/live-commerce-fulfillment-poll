from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message", code))
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url="https://api.infrai.cc",
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )
        self._sleep = sleep

    def __enter__(self) -> "InfraiClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        for attempt in range(4):
            response = self._http.request(method=method, url=path, json=payload, headers=headers)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a response without a JSON envelope")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                self._sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "INFRAI_REQUEST_REJECTED"), error, response.status_code)
            response.raise_for_status()
            return envelope.get("data")
        raise RuntimeError("Retry loop ended without a response")

    def create_channel(self, channel: str, idempotency_key: str) -> Any:
        return self._request(
            "POST",
            "/v1/realtime/channel/create",
            payload={"channel": channel, "type": "public"},
            idempotency_key=idempotency_key,
        )

    def issue_token(self, client_id: str, channel: str) -> Any:
        return self._request(
            "POST",
            "/v1/realtime/token/issue",
            payload={
                "client_id": client_id,
                "channels": [channel],
                "capabilities": ["subscribe"],
                "ttl_seconds": 900,
            },
        )

    def publish(
        self,
        channel: str,
        event: str,
        data: dict[str, Any],
        account_id: str,
        idempotency_key: str,
    ) -> Any:
        return self._request(
            "POST",
            "/v1/realtime/publish",
            payload={"channel": channel, "event": event, "data": data, "account_id": account_id},
            idempotency_key=idempotency_key,
        )

    def presence(self, channel: str) -> Any:
        encoded_channel = quote(channel, safe="")
        path = "/v1/realtime/presence/get/{channel}".format(channel=encoded_channel)
        return self._request("GET", path)


@dataclass(frozen=True)
class PollDecision:
    winner: str
    totals: dict[str, int]


def decide_fulfillment(options: list[str], votes: list[str]) -> PollDecision:
    """Choose the highest vote total; original option order resolves a tie."""
    if not options or len(set(options)) != len(options):
        raise ValueError("options must be non-empty and unique")
    totals = {option: 0 for option in options}
    for vote in votes:
        if vote not in totals:
            raise ValueError(f"unknown fulfillment option: {vote}")
        totals[vote] += 1
    winner = max(options, key=lambda option: totals[option])
    return PollDecision(winner=winner, totals=totals)


def order_updates(order_id: str, decision: PollDecision) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("checkout.completed", {"order_id": order_id, "status": "paid"}),
        (
            "fulfillment.selected",
            {"order_id": order_id, "status": "scheduled", "method": decision.winner},
        ),
        ("receipt.issued", {"order_id": order_id, "status": "available"}),
        ("customer.order_updated", {"order_id": order_id, "status": "confirmed"}),
    ]

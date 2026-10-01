import httpx
import json

from commerce_poll import InfraiClient, decide_fulfillment, order_updates


def test_create_channel_omits_vendor_override() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "data": {"channel": "commerce-session-demo"}})

    with InfraiClient("test-key", transport=httpx.MockTransport(handler)) as client:
        client.create_channel("commerce-session-demo", "session:demo:channel")

    assert json.loads(seen[0].content) == {"channel": "commerce-session-demo", "type": "public"}
    assert seen[0].headers["Idempotency-Key"] == "session:demo:channel"


def test_fulfillment_vote_drives_order_updates_with_stable_tie_break() -> None:
    decision = decide_fulfillment(
        ["store-pickup", "courier"],
        ["courier", "store-pickup"],
    )

    assert decision.winner == "store-pickup"
    assert decision.totals == {"store-pickup": 1, "courier": 1}
    assert order_updates("ord-42", decision) == [
        ("checkout.completed", {"order_id": "ord-42", "status": "paid"}),
        (
            "fulfillment.selected",
            {"order_id": "ord-42", "status": "scheduled", "method": "store-pickup"},
        ),
        ("receipt.issued", {"order_id": "ord-42", "status": "available"}),
        ("customer.order_updated", {"order_id": "ord-42", "status": "confirmed"}),
    ]


def test_publish_retries_429_with_the_same_idempotency_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"ok": False, "error": {}})
        return httpx.Response(200, json={"ok": True, "data": {"published": True}})

    client = InfraiClient("test-key", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    try:
        result = client.publish("commerce-session-demo", "poll.opened", {}, "acct-1", "event-1")
    finally:
        client.close()

    assert result == {"published": True}
    assert [request.headers["Idempotency-Key"] for request in seen] == ["event-1", "event-1"]

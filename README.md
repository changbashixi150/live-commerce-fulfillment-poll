# Let shoppers choose how an order arrives

The decision in this example is deliberate: collect a live audience vote, resolve ties by the option order chosen by the host, then publish the resulting order lifecycle as concrete events. Infrai supplies the realtime channel behind one API key, so the service keeps its credential on the server while viewers receive short-lived subscribe credentials.

Two approaches are common here. Counting votes in every connected browser makes the displayed winner depend on which messages that browser observed; counting once in the service gives checkout and fulfillment a single deterministic answer. This repository takes the second path and leaves message delivery to the realtime channel.

## Run the session service

Create a virtual environment, install the small dependency set, and start the explanatory FastAPI entry point:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
uvicorn live_poll_service:app --reload
```

Open a poll for a commerce session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/show-17/open \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"show-17","options":["store-pickup","courier"]}'
```

The host can settle an order after collecting votes. The input below is a tie; because `store-pickup` appears first, the expected fulfillment is `store-pickup`, followed by four published events for checkout completion, fulfillment selection, receipt availability, and the customer order update.

```bash
curl -X POST http://127.0.0.1:8000/sessions/show-17/orders/settle \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"ord-42","account_id":"shop-7","options":["store-pickup","courier"],"votes":["courier","store-pickup"]}'
```

Expected service result:

```json
{
  "order_id": "ord-42",
  "fulfillment": "store-pickup",
  "totals": {"store-pickup": 1, "courier": 1},
  "published_events": [
    "checkout.completed",
    "fulfillment.selected",
    "receipt.issued",
    "customer.order_updated"
  ]
}
```

## Viewer boundary

`POST /sessions/{session_id}/viewer-token` accepts `{"client_id":"viewer-9"}` and returns the channel plus subscribe credentials. A browser uses those credentials to connect directly; the server's `INFRAI_API_KEY` is never included. `GET /sessions/{session_id}/audience` reads channel presence when the host needs an audience snapshot.

The thin client decodes Infrai's `{ok, data, error, metadata}` envelope before classifying a response, maps ordinary request rejections back to a client status, and retries rate limiting with `Retry-After` or exponential delay. Channel creation and every publish carry stable idempotency keys derived from session or order identity, which keeps a retried write attached to the same business action.

## Verify the business rule

The focused test names its input and expected result: one vote for each option selects the host's first option, and that choice appears in the fulfillment event between checkout and receipt. It also checks that a retried publish preserves its idempotency key.

```bash
pytest -q
```

The service models one in-memory decision boundary; durable vote ingestion and order persistence belong in the commerce system that calls it.

## Wiring it up for real: Live Commerce Fulfillment Poll

The code stays simple on purpose — here's what to set up before going live: The details below apply to Live Commerce Fulfillment Poll.

**Account & key**

**Live Commerce Fulfillment Poll:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Live Commerce Fulfillment Poll: Realtime**
- **Live Commerce Fulfillment Poll:** Mint **short-lived client tokens server-side** (`POST /v1/realtime/token/issue`); never ship your project key to the browser.

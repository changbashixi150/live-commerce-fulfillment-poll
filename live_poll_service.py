from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from commerce_poll import InfraiClient, InfraiError, decide_fulfillment, order_updates


class OpenPollRequest(BaseModel):
    session_id: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)


class ViewerTokenRequest(BaseModel):
    client_id: str = Field(min_length=1)


class SettleOrderRequest(BaseModel):
    order_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    votes: list[str]


def channel_for(session_id: str) -> str:
    return f"commerce-session-{session_id}"


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield


app = FastAPI(title="Live commerce fulfillment poll", lifespan=lifespan)


def client_error(exc: InfraiError) -> HTTPException:
    status = exc.status_code if 400 <= exc.status_code < 500 else 502
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@app.post("/sessions/open")
def open_poll(request: OpenPollRequest) -> dict[str, Any]:
    channel = channel_for(request.session_id)
    try:
        with InfraiClient(os.environ["INFRAI_API_KEY"]) as client:
            channel_data = client.create_channel(channel, f"session:{request.session_id}:channel")
            client.publish(
                channel,
                "poll.opened",
                {"session_id": request.session_id, "options": request.options},
                request.session_id,
                f"session:{request.session_id}:poll-opened",
            )
        return {"channel": channel, "channel_data": channel_data, "options": request.options}
    except KeyError:
        raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")
    except InfraiError as exc:
        raise client_error(exc) from exc


@app.post("/sessions/{session_id}/viewer-token")
def viewer_token(session_id: str, request: ViewerTokenRequest) -> dict[str, Any]:
    try:
        with InfraiClient(os.environ["INFRAI_API_KEY"]) as client:
            token_data = client.issue_token(request.client_id, channel_for(session_id))
        return {"channel": channel_for(session_id), "credentials": token_data}
    except KeyError:
        raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")
    except InfraiError as exc:
        raise client_error(exc) from exc


@app.get("/sessions/{session_id}/audience")
def audience(session_id: str) -> dict[str, Any]:
    try:
        with InfraiClient(os.environ["INFRAI_API_KEY"]) as client:
            presence = client.presence(channel_for(session_id))
        return {"channel": channel_for(session_id), "presence": presence}
    except KeyError:
        raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")
    except InfraiError as exc:
        raise client_error(exc) from exc


@app.post("/sessions/{session_id}/orders/settle")
def settle_order(session_id: str, request: SettleOrderRequest) -> dict[str, Any]:
    try:
        decision = decide_fulfillment(request.options, request.votes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    channel = channel_for(session_id)
    updates = order_updates(request.order_id, decision)
    try:
        with InfraiClient(os.environ["INFRAI_API_KEY"]) as client:
            for sequence, (event, data) in enumerate(updates):
                client.publish(
                    channel,
                    event,
                    data,
                    request.account_id,
                    f"order:{request.order_id}:{sequence}:{event}",
                )
    except KeyError:
        raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")
    except InfraiError as exc:
        raise client_error(exc) from exc

    return {
        "order_id": request.order_id,
        "fulfillment": decision.winner,
        "totals": decision.totals,
        "published_events": [event for event, _ in updates],
    }

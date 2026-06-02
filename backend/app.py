from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


app = FastAPI(title="PricePilot API", version="0.1.0")


class WatchCreate(BaseModel):
    target: str = Field(..., description="Product URL, travel URL, hotel URL, or stock symbol")
    target_price: float
    direction: Literal["below", "above", "change"]
    contact: str


class WatchItem(WatchCreate):
    id: int
    current_price: float | None = None
    created_at: datetime


demo_watches: list[WatchItem] = [
    WatchItem(
        id=1,
        target="https://example.com/product/macbook-air",
        target_price=899,
        direction="below",
        contact="+1 217 000 0000",
        current_price=849,
        created_at=datetime.now(timezone.utc),
    )
]


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/watches")
def list_watches() -> list[WatchItem]:
    return demo_watches


@app.post("/watches")
def create_watch(payload: WatchCreate) -> WatchItem:
    watch = WatchItem(
        id=len(demo_watches) + 1,
        current_price=None,
        created_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    demo_watches.append(watch)
    return watch


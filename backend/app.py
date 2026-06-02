from datetime import datetime, timezone
import hashlib
import secrets
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


app = FastAPI(title="PricePilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserCreate(BaseModel):
    phone: str = Field(..., description="Phone number used as username and notification contact")
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    phone: str
    password: str


class UserProfile(BaseModel):
    phone: str
    created_at: datetime


class AuthResponse(BaseModel):
    token: str
    user: UserProfile


class WatchCreate(BaseModel):
    target: str = Field(..., description="Product URL, travel URL, hotel URL, or stock symbol")
    title: str = Field(default="Untitled watch")
    target_price: float
    direction: Literal["below", "above", "change"]
    contact: str | None = None


class WatchItem(WatchCreate):
    id: int
    owner_phone: str
    current_price: float | None = None
    created_at: datetime
    last_checked_at: datetime | None = None


class PricePoint(BaseModel):
    checked_at: datetime
    price: float


users: dict[str, dict[str, str | datetime]] = {}
sessions: dict[str, str] = {}
demo_watches: list[WatchItem] = []
price_history: dict[int, list[PricePoint]] = {}


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, candidate_hash = hash_password(password, salt)
    return secrets.compare_digest(candidate_hash, password_hash)


def find_user_from_token(token: str | None) -> str | None:
    if not token:
        return None
    return sessions.get(token)


def auth_error() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Invalid or missing token"})


def seed_demo_data() -> None:
    if users:
        return

    salt, password_hash = hash_password("demo1234")
    users["+1 217 000 0000"] = {
        "phone": "+1 217 000 0000",
        "salt": salt,
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc),
    }

    now = datetime.now(timezone.utc)
    initial_watches = [
        WatchItem(
            id=1,
            owner_phone="+1 217 000 0000",
            title="MacBook Air",
            target="https://example.com/product/macbook-air",
            target_price=899,
            direction="below",
            contact="+1 217 000 0000",
            current_price=849,
            created_at=now,
            last_checked_at=now,
        ),
        WatchItem(
            id=2,
            owner_phone="+1 217 000 0000",
            title="ORD 到 SFO 机票",
            target="https://example.com/flights/ord-sfo",
            target_price=280,
            direction="below",
            contact="+1 217 000 0000",
            current_price=318,
            created_at=now,
            last_checked_at=now,
        ),
        WatchItem(
            id=3,
            owner_phone="+1 217 000 0000",
            title="NVDA",
            target="NVDA",
            target_price=150,
            direction="above",
            contact="+1 217 000 0000",
            current_price=143.2,
            created_at=now,
            last_checked_at=now,
        ),
    ]
    demo_watches.extend(initial_watches)
    price_history[1] = [
        PricePoint(checked_at=now, price=979),
        PricePoint(checked_at=now, price=949),
        PricePoint(checked_at=now, price=919),
        PricePoint(checked_at=now, price=899),
        PricePoint(checked_at=now, price=869),
        PricePoint(checked_at=now, price=849),
    ]
    price_history[2] = [
        PricePoint(checked_at=now, price=355),
        PricePoint(checked_at=now, price=342),
        PricePoint(checked_at=now, price=335),
        PricePoint(checked_at=now, price=318),
    ]
    price_history[3] = [
        PricePoint(checked_at=now, price=136.4),
        PricePoint(checked_at=now, price=139.8),
        PricePoint(checked_at=now, price=143.2),
    ]


seed_demo_data()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: UserCreate) -> AuthResponse | JSONResponse:
    if payload.phone in users:
        return JSONResponse(status_code=409, content={"detail": "Phone number already registered"})

    salt, password_hash = hash_password(payload.password)
    created_at = datetime.now(timezone.utc)
    users[payload.phone] = {
        "phone": payload.phone,
        "salt": salt,
        "password_hash": password_hash,
        "created_at": created_at,
    }
    token = secrets.token_urlsafe(32)
    sessions[token] = payload.phone
    return AuthResponse(token=token, user=UserProfile(phone=payload.phone, created_at=created_at))


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse | JSONResponse:
    user = users.get(payload.phone)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Invalid phone or password"})

    is_valid = verify_password(payload.password, str(user["salt"]), str(user["password_hash"]))
    if not is_valid:
        return JSONResponse(status_code=401, content={"detail": "Invalid phone or password"})

    token = secrets.token_urlsafe(32)
    sessions[token] = payload.phone
    return AuthResponse(
        token=token,
        user=UserProfile(phone=str(user["phone"]), created_at=user["created_at"]),
    )


@app.get("/profile", response_model=UserProfile)
def profile(token: str | None = None) -> UserProfile | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    user = users[phone]
    return UserProfile(phone=str(user["phone"]), created_at=user["created_at"])


@app.get("/watches")
def list_watches(token: str | None = None) -> list[WatchItem] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    return [watch for watch in demo_watches if watch.owner_phone == phone]


@app.post("/watches")
def create_watch(payload: WatchCreate, token: str | None = None) -> WatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    current_price = round(payload.target_price * 1.08, 2)
    watch = WatchItem(
        id=len(demo_watches) + 1,
        owner_phone=phone,
        contact=payload.contact or phone,
        current_price=current_price,
        created_at=datetime.now(timezone.utc),
        last_checked_at=datetime.now(timezone.utc),
        **payload.model_dump(exclude={"contact"}),
    )
    demo_watches.append(watch)
    price_history[watch.id] = [
        PricePoint(checked_at=datetime.now(timezone.utc), price=round(current_price * 1.13, 2)),
        PricePoint(checked_at=datetime.now(timezone.utc), price=round(current_price * 1.09, 2)),
        PricePoint(checked_at=datetime.now(timezone.utc), price=current_price),
    ]
    return watch


@app.get("/watches/{watch_id}/history")
def watch_history(watch_id: int, token: str | None = None) -> list[PricePoint] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    watch = next((item for item in demo_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Watch not found"})
    return price_history.get(watch_id, [])


@app.delete("/watches/{watch_id}")
def delete_watch(watch_id: int, token: str | None = None) -> dict[str, int] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    for index, watch in enumerate(demo_watches):
        if watch.id == watch_id and watch.owner_phone == phone:
            demo_watches.pop(index)
            price_history.pop(watch_id, None)
            return {"deleted": watch_id}
    return JSONResponse(status_code=404, content={"detail": "Watch not found"})

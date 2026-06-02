from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import re
import secrets
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import requests
from bs4 import BeautifulSoup


app = FastAPI(title="PricePilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

background_checker_task: asyncio.Task | None = None


class UserCreate(BaseModel):
    phone: str = Field(..., description="Phone number used as username and notification contact")
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    phone: str
    password: str


class UserProfile(BaseModel):
    phone: str
    notification_phone: str
    avatar_data_url: str | None = None
    created_at: datetime


class UserSettingsUpdate(BaseModel):
    notification_phone: str | None = None
    avatar_data_url: str | None = None


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class AuthResponse(BaseModel):
    token: str
    user: UserProfile


class WatchCreate(BaseModel):
    target: str = Field(..., description="Product URL, travel URL, hotel URL, or stock symbol")
    title: str = Field(default="Untitled watch")
    target_price: float
    direction: Literal["below", "above", "change"]
    check_interval_minutes: int = Field(default=60, ge=5, le=10080)
    contact: str | None = None


class WatchItem(WatchCreate):
    id: int
    owner_phone: str
    current_price: float | None = None
    created_at: datetime
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    status: Literal["idle", "due", "checking", "ok", "failed"] = "idle"
    last_error: str | None = None


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
        "notification_phone": "+1 217 000 0000",
        "avatar_data_url": None,
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
            check_interval_minutes=60,
            contact="+1 217 000 0000",
            current_price=849,
            created_at=now,
            last_checked_at=now,
            next_check_at=now + timedelta(minutes=60),
            status="ok",
        ),
        WatchItem(
            id=2,
            owner_phone="+1 217 000 0000",
            title="ORD 到 SFO 机票",
            target="https://example.com/flights/ord-sfo",
            target_price=280,
            direction="below",
            check_interval_minutes=120,
            contact="+1 217 000 0000",
            current_price=318,
            created_at=now,
            last_checked_at=now,
            next_check_at=now + timedelta(minutes=120),
            status="ok",
        ),
        WatchItem(
            id=3,
            owner_phone="+1 217 000 0000",
            title="NVDA",
            target="NVDA",
            target_price=150,
            direction="above",
            check_interval_minutes=30,
            contact="+1 217 000 0000",
            current_price=143.2,
            created_at=now,
            last_checked_at=now,
            next_check_at=now + timedelta(minutes=30),
            status="ok",
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


def user_profile_from_record(user: dict[str, str | datetime]) -> UserProfile:
    return UserProfile(
        phone=str(user["phone"]),
        notification_phone=str(user.get("notification_phone") or user["phone"]),
        avatar_data_url=user.get("avatar_data_url"),
        created_at=user["created_at"],
    )


def extract_price_from_text(text: str) -> float | None:
    patterns = [
        r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"USD\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\s?(?:USD|dollars)",
    ]
    candidates: list[float] = []

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            try:
                candidates.append(float(match.replace(",", "")))
            except ValueError:
                continue

    if not candidates:
        return None
    return min(price for price in candidates if price > 0)


def fetch_latest_price(target: str) -> tuple[float | None, str | None]:
    if not target.startswith(("http://", "https://")):
        return None, "Only URL targets can be scraped in the current backend"

    try:
        response = requests.get(
            target,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
    except requests.RequestException as error:
        return None, str(error)

    soup = BeautifulSoup(response.text, "html.parser")

    selectors = [
        "[itemprop='price']",
        "[data-testid*='price' i]",
        "[class*='price' i]",
        "[id*='price' i]",
        "meta[property='product:price:amount']",
        "meta[name='price']",
    ]
    for selector in selectors:
        for element in soup.select(selector):
            raw_value = element.get("content") or element.get("value") or element.get_text(" ", strip=True)
            price = extract_price_from_text(raw_value)
            if price:
                return price, None

    body_text = soup.get_text(" ", strip=True)
    price = extract_price_from_text(body_text)
    if price:
        return price, None
    return None, "No price-like value found on page"


def refresh_watch_price(watch: WatchItem) -> WatchItem:
    watch.status = "checking"
    price, error = fetch_latest_price(watch.target)
    now = datetime.now(timezone.utc)

    if price is None:
        watch.status = "failed"
        watch.last_error = error
    else:
        watch.current_price = price
        watch.status = "ok"
        watch.last_error = None
        price_history.setdefault(watch.id, []).append(PricePoint(checked_at=now, price=price))

    watch.last_checked_at = now
    watch.next_check_at = now + timedelta(minutes=watch.check_interval_minutes)
    return watch


def run_due_checks(owner_phone: str | None = None) -> list[WatchItem]:
    now = datetime.now(timezone.utc)
    refreshed: list[WatchItem] = []
    for watch in demo_watches:
        if owner_phone and watch.owner_phone != owner_phone:
            continue
        if watch.next_check_at and watch.next_check_at <= now:
            refreshed.append(refresh_watch_price(watch))
    return refreshed


async def background_price_checker() -> None:
    while True:
        run_due_checks()
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_background_checker() -> None:
    global background_checker_task
    background_checker_task = asyncio.create_task(background_price_checker())


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
        "notification_phone": payload.phone,
        "avatar_data_url": None,
        "salt": salt,
        "password_hash": password_hash,
        "created_at": created_at,
    }
    token = secrets.token_urlsafe(32)
    sessions[token] = payload.phone
    return AuthResponse(token=token, user=user_profile_from_record(users[payload.phone]))


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
        user=user_profile_from_record(user),
    )


@app.get("/profile", response_model=UserProfile)
def profile(token: str | None = None) -> UserProfile | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    return user_profile_from_record(users[phone])


@app.patch("/profile", response_model=UserProfile)
def update_profile(payload: UserSettingsUpdate, token: str | None = None) -> UserProfile | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    user = users[phone]
    if payload.notification_phone is not None:
        user["notification_phone"] = payload.notification_phone
    if payload.avatar_data_url is not None:
        user["avatar_data_url"] = payload.avatar_data_url
    return user_profile_from_record(user)


@app.patch("/profile/password")
def update_password(payload: PasswordUpdate, token: str | None = None) -> dict[str, str] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    user = users[phone]
    is_valid = verify_password(payload.current_password, str(user["salt"]), str(user["password_hash"]))
    if not is_valid:
        return JSONResponse(status_code=401, content={"detail": "Current password is incorrect"})
    salt, password_hash = hash_password(payload.new_password)
    user["salt"] = salt
    user["password_hash"] = password_hash
    return {"status": "password updated"}


@app.get("/watches")
def list_watches(token: str | None = None) -> list[WatchItem] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    run_due_checks(phone)
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
        next_check_at=datetime.now(timezone.utc) + timedelta(minutes=payload.check_interval_minutes),
        status="ok",
        **payload.model_dump(exclude={"contact"}),
    )
    demo_watches.append(watch)
    price_history[watch.id] = [
        PricePoint(checked_at=datetime.now(timezone.utc), price=round(current_price * 1.13, 2)),
        PricePoint(checked_at=datetime.now(timezone.utc), price=round(current_price * 1.09, 2)),
        PricePoint(checked_at=datetime.now(timezone.utc), price=current_price),
    ]
    return watch


@app.post("/watches/{watch_id}/refresh")
def refresh_watch(watch_id: int, token: str | None = None) -> WatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    watch = next((item for item in demo_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Watch not found"})
    return refresh_watch_price(watch)


@app.post("/jobs/run-due-checks")
def run_due_check_job(token: str | None = None) -> dict[str, int] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    refreshed = run_due_checks(phone)
    return {"refreshed": len(refreshed)}


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

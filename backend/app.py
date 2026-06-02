import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
import re
import secrets
from urllib.parse import urljoin
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
import requests
from bs4 import BeautifulSoup
from backend.scrapers import PriceCandidate, extract_price_candidates, fetch_selected_price


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
    id: int | None = None
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
    extraction_key: str | None = None
    extraction_strategy: str | None = None
    extraction_selector: str | None = None
    extraction_label: str | None = None
    extraction_confidence: float | None = None


class WatchItem(WatchCreate):
    id: int
    owner_phone: str
    current_price: float | None = None
    created_at: datetime
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    status: Literal["idle", "due", "checking", "ok", "failed"] = "idle"
    last_error: str | None = None
    last_candidates: list[dict[str, str | float | None]] = Field(default_factory=list)


class ExtractPreviewRequest(BaseModel):
    target: str


class ExtractPreviewResponse(BaseModel):
    target: str
    candidates: list[dict[str, str | float | None]]
    error: str | None = None


class PricePoint(BaseModel):
    checked_at: datetime
    price: float


class WatchIntervalUpdate(BaseModel):
    check_interval_minutes: int = Field(..., ge=5, le=10080)


class StoreWatchCreate(BaseModel):
    store_url: str
    title: str = "Store discovery watch"
    keywords: str = Field(default="", description="Comma or space separated interests")
    min_score: float = Field(default=80, ge=0, le=100)
    check_interval_minutes: int = Field(default=360, ge=15, le=10080)


class StoreWatchItem(StoreWatchCreate):
    id: int
    owner_phone: str
    created_at: datetime
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    status: Literal["idle", "due", "checking", "ok", "failed"] = "idle"
    last_error: str | None = None


class DiscoveredProduct(BaseModel):
    id: int
    store_watch_id: int
    title: str
    url: str
    image_url: str | None = None
    price: float | None = None
    score: float
    matched: bool
    discovered_at: datetime


class NotificationEvent(BaseModel):
    id: int
    owner_phone: str
    kind: Literal["price", "product_match"]
    title: str
    message: str
    created_at: datetime
    read: bool = False


users: dict[str, dict[str, str | datetime]] = {}
sessions: dict[str, str] = {}
demo_watches: list[WatchItem] = []
price_history: dict[int, list[PricePoint]] = {}
store_watches: list[StoreWatchItem] = []
discovered_products: list[DiscoveredProduct] = []
notification_events: list[NotificationEvent] = []
DATABASE_URL = os.getenv("DATABASE_URL")


def database_enabled() -> bool:
    return bool(DATABASE_URL)


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_database() -> None:
    if not database_enabled():
        return
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id BIGSERIAL PRIMARY KEY,
                  phone TEXT UNIQUE NOT NULL,
                  notification_phone TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  password_salt TEXT NOT NULL,
                  avatar_url TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()


def db_get_user(phone: str) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, phone, notification_phone, password_hash, password_salt, avatar_url, created_at
                FROM users
                WHERE phone = %s
                """,
                (phone,),
            )
            return cur.fetchone()


def db_create_user(phone: str, salt: str, password_hash: str) -> dict:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (phone, notification_phone, password_hash, password_salt)
                VALUES (%s, %s, %s, %s)
                RETURNING id, phone, notification_phone, password_hash, password_salt, avatar_url, created_at
                """,
                (phone, phone, password_hash, salt),
            )
            user = cur.fetchone()
        conn.commit()
    return user


def db_update_profile(
    phone: str,
    notification_phone: str | None = None,
    avatar_data_url: str | None = None,
) -> dict:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                  notification_phone = COALESCE(%s, notification_phone),
                  avatar_url = COALESCE(%s, avatar_url),
                  updated_at = now()
                WHERE phone = %s
                RETURNING id, phone, notification_phone, password_hash, password_salt, avatar_url, created_at
                """,
                (notification_phone, avatar_data_url, phone),
            )
            user = cur.fetchone()
        conn.commit()
    return user


def db_update_password(phone: str, salt: str, password_hash: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET password_salt = %s, password_hash = %s, updated_at = now()
                WHERE phone = %s
                """,
                (salt, password_hash, phone),
            )
        conn.commit()


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
    store_watches.append(
        StoreWatchItem(
            id=1,
            owner_phone="+1 217 000 0000",
            title="Tech accessories discovery",
            store_url="https://example.com/store",
            keywords="laptop sleeve keyboard usb-c charger",
            min_score=80,
            check_interval_minutes=360,
            created_at=now,
            last_checked_at=now,
            next_check_at=now + timedelta(minutes=360),
            status="idle",
        )
    )


seed_demo_data()


def user_profile_from_record(user: dict[str, str | datetime]) -> UserProfile:
    return UserProfile(
        id=user.get("id"),
        phone=str(user["phone"]),
        notification_phone=str(user.get("notification_phone") or user["phone"]),
        avatar_data_url=user.get("avatar_data_url") or user.get("avatar_url"),
        created_at=user["created_at"],
    )


def extract_price_from_text(text: str) -> float | None:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return None

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
    valid_candidates = [price for price in candidates if 0 < price < 1_000_000]
    if not valid_candidates:
        return None
    return valid_candidates[0]


def parse_numeric_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)", value)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())


def text_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1 if digest[2] % 2 == 0 else -1
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def build_user_profile_text(owner_phone: str) -> str:
    watch_text = " ".join(
        f"{watch.title} {watch.target}" for watch in demo_watches if watch.owner_phone == owner_phone
    )
    store_text = " ".join(
        f"{watch.title} {watch.keywords}" for watch in store_watches if watch.owner_phone == owner_phone
    )
    liked_products = " ".join(
        product.title for product in discovered_products if product.matched
    )
    return f"{watch_text} {store_text} {liked_products}".strip()


def extract_stock_symbol(target: str) -> str | None:
    direct_symbol = re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?", target.strip().upper())
    if direct_symbol:
        return direct_symbol.group(0)

    stock_patterns = [
        r"/stocks/([A-Z]{1,6}(?:\.[A-Z])?)",
        r"/quote/([A-Z]{1,6}(?:\.[A-Z])?)",
        r"symbol=([A-Z]{1,6}(?:\.[A-Z])?)",
    ]
    for pattern in stock_patterns:
        match = re.search(pattern, target, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def fetch_stock_price(symbol: str) -> tuple[float | None, str | None]:
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 PricePilot/0.1"},
        )
        response.raise_for_status()
        results = response.json().get("quoteResponse", {}).get("result", [])
    except requests.RequestException as error:
        return None, str(error)
    except ValueError:
        return None, "Invalid stock quote response"

    if not results:
        return None, f"No quote found for {symbol}"
    price = results[0].get("regularMarketPrice") or results[0].get("postMarketPrice")
    if price is None:
        return None, f"No market price found for {symbol}"
    return float(price), None


def fetch_latest_price(
    target: str,
    key: str | None = None,
    strategy: str | None = None,
    selector: str | None = None,
) -> tuple[float | None, str | None, list[dict[str, str | float | None]]]:
    price, error, candidates = fetch_selected_price(target, key=key, strategy=strategy, selector=selector)
    return price, error, [candidate.__dict__ for candidate in candidates]


def scrape_store_products(store_url: str) -> tuple[list[dict[str, str | float | None]], str | None]:
    if not store_url.startswith(("http://", "https://")):
        return [], "Store watch requires a URL"

    try:
        response = requests.get(
            store_url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
    except requests.RequestException as error:
        return [], str(error)

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = soup.select(
        "[class*='product' i], [data-testid*='product' i], [class*='item' i], article, li"
    )
    products: list[dict[str, str | float | None]] = []
    seen_urls: set[str] = set()

    for element in candidates[:120]:
        title_node = element.select_one("h1, h2, h3, h4, [class*='title' i], [class*='name' i], a")
        link_node = element.select_one("a[href]")
        image_node = element.select_one("img")
        title = title_node.get_text(" ", strip=True) if title_node else element.get_text(" ", strip=True)[:90]
        href = link_node.get("href") if link_node else store_url
        product_url = urljoin(store_url, href)
        if not title or len(title) < 3 or product_url in seen_urls:
            continue
        seen_urls.add(product_url)
        image_src = image_node.get("src") or image_node.get("data-src") if image_node else None
        products.append(
            {
                "title": title[:180],
                "url": product_url,
                "image_url": urljoin(store_url, image_src) if image_src else None,
                "price": extract_price_from_text(element.get_text(" ", strip=True)),
            }
        )

    if not products:
        return [], "No product-like items found on store page"
    return products[:40], None


def refresh_watch_price(watch: WatchItem) -> WatchItem:
    watch.status = "checking"
    price, error, candidates = fetch_latest_price(
        watch.target,
        key=watch.extraction_key,
        strategy=watch.extraction_strategy,
        selector=watch.extraction_selector,
    )
    now = datetime.now(timezone.utc)
    watch.last_candidates = candidates

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


def refresh_store_watch(watch: StoreWatchItem) -> StoreWatchItem:
    watch.status = "checking"
    products, error = scrape_store_products(watch.store_url)
    now = datetime.now(timezone.utc)
    if error:
        watch.status = "failed"
        watch.last_error = error
    else:
        profile_embedding = text_embedding(f"{watch.keywords} {build_user_profile_text(watch.owner_phone)}")
        known_urls = {
            product.url for product in discovered_products if product.store_watch_id == watch.id
        }
        for product in products:
            if str(product["url"]) in known_urls:
                continue
            product_embedding = text_embedding(
                f"{product['title']} {product.get('url') or ''} {product.get('image_url') or ''}"
            )
            score = round(max(cosine_similarity(profile_embedding, product_embedding), 0) * 100, 1)
            matched = score >= watch.min_score
            discovered = DiscoveredProduct(
                id=len(discovered_products) + 1,
                store_watch_id=watch.id,
                title=str(product["title"]),
                url=str(product["url"]),
                image_url=product.get("image_url"),
                price=product.get("price"),
                score=score,
                matched=matched,
                discovered_at=now,
            )
            discovered_products.append(discovered)
            if matched:
                notification_events.append(
                    NotificationEvent(
                        id=len(notification_events) + 1,
                        owner_phone=watch.owner_phone,
                        kind="product_match",
                        title=f"New product match: {discovered.title}",
                        message=f"{discovered.title} scored {discovered.score}/100 for {watch.title}",
                        created_at=now,
                    )
                )
        watch.status = "ok"
        watch.last_error = None

    watch.last_checked_at = now
    watch.next_check_at = now + timedelta(minutes=watch.check_interval_minutes)
    return watch


def run_due_store_checks(owner_phone: str | None = None) -> list[StoreWatchItem]:
    now = datetime.now(timezone.utc)
    refreshed: list[StoreWatchItem] = []
    for watch in store_watches:
        if owner_phone and watch.owner_phone != owner_phone:
            continue
        if watch.next_check_at and watch.next_check_at <= now:
            refreshed.append(refresh_store_watch(watch))
    return refreshed


async def background_price_checker() -> None:
    while True:
        run_due_checks()
        run_due_store_checks()
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_background_checker() -> None:
    global background_checker_task
    init_database()
    background_checker_task = asyncio.create_task(background_price_checker())


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract/preview", response_model=ExtractPreviewResponse)
def preview_extraction(payload: ExtractPreviewRequest) -> ExtractPreviewResponse:
    candidates, error = extract_price_candidates(payload.target)
    return ExtractPreviewResponse(
        target=payload.target,
        candidates=[candidate.__dict__ for candidate in candidates],
        error=error,
    )


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: UserCreate) -> AuthResponse | JSONResponse:
    if database_enabled():
        existing_user = db_get_user(payload.phone)
        if existing_user:
            return JSONResponse(status_code=409, content={"detail": "Phone number already registered"})
        salt, password_hash = hash_password(payload.password)
        user = db_create_user(payload.phone, salt, password_hash)
        token = secrets.token_urlsafe(32)
        sessions[token] = payload.phone
        return AuthResponse(token=token, user=user_profile_from_record(user))

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
    if database_enabled():
        user = db_get_user(payload.phone)
        if not user:
            return JSONResponse(status_code=401, content={"detail": "Invalid phone or password"})
        is_valid = verify_password(payload.password, str(user["password_salt"]), str(user["password_hash"]))
        if not is_valid:
            return JSONResponse(status_code=401, content={"detail": "Invalid phone or password"})
        token = secrets.token_urlsafe(32)
        sessions[token] = payload.phone
        return AuthResponse(token=token, user=user_profile_from_record(user))

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
    if database_enabled():
        user = db_get_user(phone)
        if not user:
            return auth_error()
        return user_profile_from_record(user)
    return user_profile_from_record(users[phone])


@app.patch("/profile", response_model=UserProfile)
def update_profile(payload: UserSettingsUpdate, token: str | None = None) -> UserProfile | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    if database_enabled():
        user = db_update_profile(
            phone,
            notification_phone=payload.notification_phone,
            avatar_data_url=payload.avatar_data_url,
        )
        if not user:
            return auth_error()
        return user_profile_from_record(user)

    user = users[phone]
    if payload.notification_phone is not None:
        user["notification_phone"] = payload.notification_phone
    if payload.avatar_data_url is not None:
        user["avatar_data_url"] = payload.avatar_data_url
    return user_profile_from_record(user)


@app.patch("/profile/password", response_model=None)
def update_password(payload: PasswordUpdate, token: str | None = None) -> dict[str, str] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    if database_enabled():
        user = db_get_user(phone)
        if not user:
            return auth_error()
        is_valid = verify_password(payload.current_password, str(user["password_salt"]), str(user["password_hash"]))
        if not is_valid:
            return JSONResponse(status_code=401, content={"detail": "Current password is incorrect"})
        salt, password_hash = hash_password(payload.new_password)
        db_update_password(phone, salt, password_hash)
        return {"status": "password updated"}

    user = users[phone]
    is_valid = verify_password(payload.current_password, str(user["salt"]), str(user["password_hash"]))
    if not is_valid:
        return JSONResponse(status_code=401, content={"detail": "Current password is incorrect"})
    salt, password_hash = hash_password(payload.new_password)
    user["salt"] = salt
    user["password_hash"] = password_hash
    return {"status": "password updated"}


@app.get("/watches", response_model=None)
def list_watches(token: str | None = None) -> list[WatchItem] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    run_due_checks(phone)
    return [watch for watch in demo_watches if watch.owner_phone == phone]


@app.post("/watches", response_model=None)
def create_watch(payload: WatchCreate, token: str | None = None) -> WatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    fetched_price, fetch_error, candidates = fetch_latest_price(
        payload.target,
        key=payload.extraction_key,
        strategy=payload.extraction_strategy,
        selector=payload.extraction_selector,
    )
    now = datetime.now(timezone.utc)
    watch = WatchItem(
        id=len(demo_watches) + 1,
        owner_phone=phone,
        contact=payload.contact or phone,
        current_price=fetched_price,
        created_at=now,
        last_checked_at=now if fetched_price is not None or fetch_error else None,
        next_check_at=now + timedelta(minutes=payload.check_interval_minutes),
        status="ok" if fetched_price is not None else "failed",
        last_error=fetch_error,
        last_candidates=candidates,
        **payload.model_dump(exclude={"contact"}),
    )
    demo_watches.append(watch)
    price_history[watch.id] = []
    if fetched_price is not None:
        price_history[watch.id].append(PricePoint(checked_at=now, price=fetched_price))
    return watch


@app.patch("/watches/{watch_id}/interval", response_model=None)
def update_watch_interval(
    watch_id: int, payload: WatchIntervalUpdate, token: str | None = None
) -> WatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    watch = next((item for item in demo_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Watch not found"})
    watch.check_interval_minutes = payload.check_interval_minutes
    watch.next_check_at = datetime.now(timezone.utc) + timedelta(minutes=payload.check_interval_minutes)
    return watch


@app.post("/watches/{watch_id}/refresh", response_model=None)
def refresh_watch(watch_id: int, token: str | None = None) -> WatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    watch = next((item for item in demo_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Watch not found"})
    return refresh_watch_price(watch)


@app.post("/jobs/run-due-checks", response_model=None)
def run_due_check_job(token: str | None = None) -> dict[str, int] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    refreshed = run_due_checks(phone)
    store_refreshed = run_due_store_checks(phone)
    return {"refreshed": len(refreshed), "store_refreshed": len(store_refreshed)}


@app.get("/store-watches", response_model=None)
def list_store_watches(token: str | None = None) -> list[StoreWatchItem] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    run_due_store_checks(phone)
    return [watch for watch in store_watches if watch.owner_phone == phone]


@app.post("/store-watches", response_model=None)
def create_store_watch(payload: StoreWatchCreate, token: str | None = None) -> StoreWatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    now = datetime.now(timezone.utc)
    watch = StoreWatchItem(
        id=len(store_watches) + 1,
        owner_phone=phone,
        created_at=now,
        next_check_at=now + timedelta(minutes=payload.check_interval_minutes),
        **payload.model_dump(),
    )
    store_watches.append(watch)
    return refresh_store_watch(watch)


@app.post("/store-watches/{watch_id}/refresh", response_model=None)
def refresh_store_watch_endpoint(watch_id: int, token: str | None = None) -> StoreWatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    watch = next((item for item in store_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Store watch not found"})
    return refresh_store_watch(watch)


@app.patch("/store-watches/{watch_id}/interval", response_model=None)
def update_store_watch_interval(
    watch_id: int, payload: WatchIntervalUpdate, token: str | None = None
) -> StoreWatchItem | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    watch = next((item for item in store_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Store watch not found"})
    watch.check_interval_minutes = payload.check_interval_minutes
    watch.next_check_at = datetime.now(timezone.utc) + timedelta(minutes=payload.check_interval_minutes)
    return watch


@app.delete("/store-watches/{watch_id}", response_model=None)
def delete_store_watch(watch_id: int, token: str | None = None) -> dict[str, int] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    for index, watch in enumerate(store_watches):
        if watch.id == watch_id and watch.owner_phone == phone:
            store_watches.pop(index)
            return {"deleted": watch_id}
    return JSONResponse(status_code=404, content={"detail": "Store watch not found"})


@app.get("/store-watches/{watch_id}/products", response_model=None)
def list_discovered_products(watch_id: int, token: str | None = None) -> list[DiscoveredProduct] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    watch = next((item for item in store_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Store watch not found"})
    return [product for product in discovered_products if product.store_watch_id == watch_id]


@app.get("/notifications", response_model=None)
def list_notifications(token: str | None = None) -> list[NotificationEvent] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()
    return [event for event in notification_events if event.owner_phone == phone]


@app.get("/watches/{watch_id}/history", response_model=None)
def watch_history(watch_id: int, token: str | None = None) -> list[PricePoint] | JSONResponse:
    phone = find_user_from_token(token)
    if not phone:
        return auth_error()

    watch = next((item for item in demo_watches if item.id == watch_id and item.owner_phone == phone), None)
    if not watch:
        return JSONResponse(status_code=404, content={"detail": "Watch not found"})
    return price_history.get(watch_id, [])


@app.delete("/watches/{watch_id}", response_model=None)
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

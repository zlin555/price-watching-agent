from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class PriceCandidate:
    price: float
    label: str
    strategy: str
    selector: str | None = None
    confidence: float = 0.5
    snippet: str | None = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)


def extract_stock_symbol(target: str) -> str | None:
    direct_symbol = re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?", target.strip().upper())
    if direct_symbol:
        return direct_symbol.group(0)

    for pattern in [
        r"/stocks/([A-Z]{1,6}(?:\.[A-Z])?)",
        r"/quote/([A-Z]{1,6}(?:\.[A-Z])?)",
        r"symbol=([A-Z]{1,6}(?:\.[A-Z])?)",
    ]:
        match = re.search(pattern, target, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def fetch_stock_candidate(symbol: str) -> PriceCandidate | None:
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}",
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        results = response.json().get("quoteResponse", {}).get("result", [])
    except (requests.RequestException, ValueError):
        return None

    if not results:
        return None
    raw_price = results[0].get("regularMarketPrice") or results[0].get("postMarketPrice")
    if raw_price is None:
        return None
    price = float(raw_price)
    return PriceCandidate(
        price=price,
        label=f"{symbol} market price ${price}",
        strategy="stock_api",
        selector=symbol,
        confidence=0.98,
        snippet=f"Yahoo Finance quote for {symbol}",
    )


def parse_numeric_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)", value)
    if not match:
        return None
    try:
        price = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if 0 < price < 1_000_000:
        return price
    return None


def prices_from_text(text: str) -> list[float]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []

    patterns = [
        r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)",
        r"USD\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)",
        r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)\s?(?:USD|dollars)",
    ]
    prices: list[float] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            price = parse_numeric_price(match)
            if price is not None:
                prices.append(price)
    return prices


def add_candidate(
    candidates: list[PriceCandidate],
    seen: set[tuple[float, str, str | None]],
    price: float | None,
    label: str,
    strategy: str,
    selector: str | None,
    confidence: float,
    snippet: str | None = None,
) -> None:
    if price is None:
        return
    key = (round(price, 4), strategy, selector)
    if key in seen:
        return
    seen.add(key)
    candidates.append(
        PriceCandidate(
            price=price,
            label=label[:160],
            strategy=strategy,
            selector=selector,
            confidence=round(confidence, 2),
            snippet=snippet[:240] if snippet else None,
        )
    )


def load_soup(url: str) -> tuple[BeautifulSoup | None, str | None]:
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except requests.RequestException as error:
        return None, str(error)
    return BeautifulSoup(response.text, "html.parser"), None


def extract_json_ld_prices(soup: BeautifulSoup, candidates: list[PriceCandidate], seen: set[tuple[float, str, str | None]]) -> None:
    for index, script in enumerate(soup.select("script[type='application/ld+json']")):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = None

        values: list[Any] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if "price" in node:
                    values.append(node["price"])
                if "lowPrice" in node:
                    values.append(node["lowPrice"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        if payload is not None:
            walk(payload)
        else:
            values.extend(re.findall(r'"(?:price|lowPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', raw))

        for value in values:
            price = parse_numeric_price(str(value))
            add_candidate(
                candidates,
                seen,
                price,
                f"Structured product price ${price}",
                "json_ld",
                f"script[type='application/ld+json']:eq({index})",
                0.92,
                raw,
            )


def extract_meta_prices(soup: BeautifulSoup, candidates: list[PriceCandidate], seen: set[tuple[float, str, str | None]]) -> None:
    selectors = [
        "meta[property='product:price:amount']",
        "meta[property='og:price:amount']",
        "meta[name='twitter:data1']",
        "meta[name='price']",
    ]
    for selector in selectors:
        for element in soup.select(selector):
            content = element.get("content")
            price = parse_numeric_price(content)
            add_candidate(candidates, seen, price, f"Meta price ${price}", "meta", selector, 0.86, content)


def extract_selector_prices(soup: BeautifulSoup, candidates: list[PriceCandidate], seen: set[tuple[float, str, str | None]]) -> None:
    selectors = [
        "[itemprop='price']",
        "[data-testid*='price' i]",
        "[class*='price' i]",
        "[id*='price' i]",
        "[aria-label*='price' i]",
    ]
    for selector in selectors:
        for element in soup.select(selector)[:30]:
            raw = (
                element.get("content")
                or element.get("value")
                or element.get("aria-label")
                or element.get_text(" ", strip=True)
            )
            context = element.parent.get_text(" ", strip=True) if element.parent else raw
            for price in prices_from_text(raw) or prices_from_text(context):
                add_candidate(
                    candidates,
                    seen,
                    price,
                    f"{raw[:80]}",
                    "selector",
                    selector,
                    0.72,
                    context,
                )


def extract_text_prices(soup: BeautifulSoup, candidates: list[PriceCandidate], seen: set[tuple[float, str, str | None]]) -> None:
    priority_text = " ".join(
        node.get_text(" ", strip=True)
        for node in soup.select("h1, h2, [class*='hero' i], [class*='quote' i], [class*='stock' i]")
    )
    for price in prices_from_text(priority_text):
        add_candidate(candidates, seen, price, f"Prominent page text ${price}", "text", "prominent-text", 0.55, priority_text)

    if len(candidates) >= 8:
        return

    body_text = soup.get_text(" ", strip=True)
    for price in prices_from_text(body_text)[:12]:
        add_candidate(candidates, seen, price, f"Page text ${price}", "text", "body-text", 0.3, body_text[:500])


def extract_price_candidates(target: str) -> tuple[list[PriceCandidate], str | None]:
    symbol = extract_stock_symbol(target)
    if symbol:
        stock_candidate = fetch_stock_candidate(symbol)
        if stock_candidate:
            return [stock_candidate], None
        if not target.startswith(("http://", "https://")):
            return [], f"No quote found for {symbol}"

    if not target.startswith(("http://", "https://")):
        return [], "Only URL targets or stock symbols can be extracted"

    soup, error = load_soup(target)
    if error or soup is None:
        return [], error

    candidates: list[PriceCandidate] = []
    seen: set[tuple[float, str, str | None]] = set()
    extract_json_ld_prices(soup, candidates, seen)
    extract_meta_prices(soup, candidates, seen)
    extract_selector_prices(soup, candidates, seen)
    extract_text_prices(soup, candidates, seen)
    candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return candidates[:20], None if candidates else "No price candidates found"


def fetch_selected_price(
    target: str,
    strategy: str | None = None,
    selector: str | None = None,
) -> tuple[float | None, str | None, list[PriceCandidate]]:
    candidates, error = extract_price_candidates(target)
    if error and not candidates:
        return None, error, candidates

    if strategy:
        for candidate in candidates:
            if candidate.strategy == strategy and (selector is None or candidate.selector == selector):
                return candidate.price, None, candidates

    if candidates:
        return candidates[0].price, None, candidates
    return None, error or "No price candidates found", candidates

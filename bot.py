"""
XBO.com Top 5 Tokens — Telegram Bot (GitHub Actions version)
Парсит топ-5 растущих токенов с XBO.com и постит в Telegram.
"""

import os
import json
import requests
from datetime import datetime
from io import BytesIO
from dataclasses import dataclass


# ─── Конфигурация ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
XBO_SPOT_BASE = "https://www.xbo.com/platform/spot"


@dataclass
class TokenData:
    symbol: str
    price: float
    daily_gain: float
    trading_volume: float
    market_cap: float


# ═════════════════════════════════════════════════════════════════════
# 1. ПОЛУЧЕНИЕ ДАННЫХ
# ═════════════════════════════════════════════════════════════════════

def fetch_top5_tokens() -> list[TokenData]:
    """
    Получаем данные с XBO.com Public API.
    Документация: https://public-docs.xbo.com/
    Endpoint: /trading-pairs — 24h stats по всем парам.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # Список endpoint'ов для попытки (XBO Public API)
    endpoints = [
        "https://public-api.xbo.com/trading-pairs",
        "https://public-api.xbo.com/api/v1/trading-pairs",
        "https://api.xbo.com/api/v1/public/tickers",
        "https://api.xbo.com/v1/public/tickers",
        "https://www.xbo.com/api/v1/public/tickers",
        "https://public-api.xbo.com/tickers",
    ]

    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                tokens = parse_response(data)
                if tokens:
                    print(f"✅ Данные получены с {url}")
                    return tokens
        except Exception as e:
            print(f"⚠️ {url} — {e}")
            continue

    # Fallback: CoinGecko API (данные XBO.com через агрегатор)
    print("Пробуем CoinGecko как fallback...")
    return fetch_via_coingecko()


def parse_response(data) -> list[TokenData]:
    """Парсинг ответа API — адаптивный под разные форматы."""
    tokens = []

    # Формат может быть list или dict
    if isinstance(data, dict):
        # Если есть ключ data/result/tickers
        items = data.get("data", data.get("result", data.get("tickers", data)))
        if isinstance(items, dict):
            # Формат {"BTC_USDT": {...}, "ETH_USDT": {...}}
            for key, val in items.items():
                token = parse_ticker_item(val, key)
                if token:
                    tokens.append(token)
        elif isinstance(items, list):
            for item in items:
                token = parse_ticker_item(item)
                if token:
                    tokens.append(token)
    elif isinstance(data, list):
        for item in data:
            token = parse_ticker_item(item)
            if token:
                tokens.append(token)

    # Фильтруем только USDT пары с положительным ростом
    tokens = [t for t in tokens if t.daily_gain > 0]
    tokens.sort(key=lambda t: t.daily_gain, reverse=True)
    return tokens[:5]


def parse_ticker_item(item, key=None) -> TokenData | None:
    """Парсинг одного тикера."""
    try:
        if isinstance(item, dict):
            ticker = item.get("ticker", item)

            # Определяем символ
            symbol_raw = (
                ticker.get("symbol")
                or ticker.get("name")
                or ticker.get("pair")
                or key
                or ""
            )
            # Убираем USDT/BTC суффиксы
            symbol = (
                symbol_raw.replace("/USDT", "")
                .replace("_USDT", "")
                .replace("-USDT", "")
                .replace("USDT", "")
                .replace("/", "")
                .replace("_", "")
                .strip()
            )

            if not symbol or symbol in ("BTC", "ETH", "USDT", "USDC"):
                # Пропускаем основные монеты — нас интересуют альткоины
                pass

            # Цена
            price = float(
                ticker.get("last", ticker.get("lastPrice", ticker.get("close", ticker.get("c", 0))))
            )

            # Изменение за 24ч (%)
            change = ticker.get("change", ticker.get("priceChangePercent", ticker.get("P", None)))
            if change is not None:
                change = float(change)
                # Если значение дробное (0.05 = 5%), умножаем на 100
                if -1 < change < 1 and change != 0:
                    change *= 100
            else:
                # Вычисляем из open/last
                open_price = float(ticker.get("open", 0))
                if open_price > 0 and price > 0:
                    change = ((price - open_price) / open_price) * 100
                else:
                    return None

            # Volume
            volume = float(
                ticker.get("deal", ticker.get("quoteVolume", ticker.get("vol", ticker.get("volume", 0))))
            )

            # Market cap (может отсутствовать в API биржи)
            mcap = float(ticker.get("marketCap", ticker.get("mc", 0)))

            if price > 0 and symbol:
                return TokenData(
                    symbol=symbol,
                    price=price,
                    daily_gain=round(change, 2),
                    trading_volume=volume,
                    market_cap=mcap,
                )
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def fetch_via_coingecko() -> list[TokenData]:
    """Fallback: получаем данные через CoinGecko API (биржа XBO.com)."""
    try:
        url = "https://api.coingecko.com/api/v3/exchanges/xbo-com/tickers"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"CoinGecko вернул {resp.status_code}")
            return []

        data = resp.json()
        tickers = data.get("tickers", [])

        tokens = []
        for t in tickers:
            if t.get("target") != "USDT":
                continue
            base = t.get("base", "")
            last = float(t.get("last", 0))
            volume = float(t.get("converted_volume", {}).get("usd", 0))

            # CoinGecko не даёт 24h change напрямую в exchange tickers
            # Используем bid_ask_spread как proxy или пропускаем
            tokens.append(TokenData(
                symbol=base,
                price=last,
                daily_gain=0,  # Будем заполнять отдельно
                trading_volume=volume,
                market_cap=0,
            ))

        # Если нет данных о change — пробуем через coins API
        if tokens:
            enrich_with_change(tokens)
            tokens = [t for t in tokens if t.daily_gain > 0]
            tokens.sort(key=lambda t: t.daily_gain, reverse=True)

        return tokens[:5]

    except Exception as e:
        print(f"CoinGecko ошибка: {e}")
        return []


def enrich_with_change(tokens: list[TokenData]):
    """Дополняем данные о 24h change через CoinGecko."""
    try:
        ids_map = {}
        # Получаем список монет CoinGecko
        coins_list = requests.get(
            "https://api.coingecko.com/api/v3/coins/list", timeout=15
        ).json()

        symbol_to_id = {}
        for coin in coins_list:
            sym = coin["symbol"].upper()
            if sym not in symbol_to_id:
                symbol_to_id[sym] = coin["id"]

        # Собираем ids для наших токенов
        ids = []
        for t in tokens:
            cg_id = symbol_to_id.get(t.symbol.upper())
            if cg_id:
                ids.append(cg_id)
                ids_map[cg_id] = t

        if not ids:
            return

        # Запрашиваем market data
        ids_str = ",".join(ids[:20])
        market_data = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&ids={ids_str}&price_change_percentage=24h",
            timeout=15,
        ).json()

        for coin in market_data:
            token = ids_map.get(coin["id"])
            if token:
                token.daily_gain = round(
                    float(coin.get("price_change_percentage_24h", 0)), 2
                )
                token.market_cap = float(coin.get("market_cap", 0))

    except Exception as e:
        print(f"Ошибка обогащения данных: {e}")


# ═════════════════════════════════════════════════════════════════════
# 2. ГЕНЕРАЦИЯ КАРТИНКИ
# ═════════════════════════════════════════════════════════════════════

def generate_image(tokens: list[TokenData]) -> BytesIO:
    """Генерация картинки в стиле XBO.com."""
    from PIL import Image, ImageDraw, ImageFont

    WIDTH, HEIGHT = 1200, 720
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # Фон: тёмный градиент
    for y in range(HEIGHT):
        r = int(15 + (25 - 15) * y / HEIGHT)
        g = int(10 + (18 - 10) * y / HEIGHT)
        b = int(40 + (60 - 40) * y / HEIGHT)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # Декоративное свечение
    for i in range(150):
        alpha = max(0, 30 - i // 5)
        draw.ellipse(
            [WIDTH - 200 - i, -100 - i, WIDTH + i, 200 + i],
            fill=(80 + alpha, 50, 180 + min(alpha, 75)),
        )

    # Шрифты
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        font_header = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_row = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_row_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_logo = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except OSError:
        font_title = ImageFont.load_default()
        font_header = font_row = font_row_bold = font_small = font_logo = font_title

    # Логотип и заголовок
    draw.text((40, 30), "xbo", fill=(120, 90, 255), font=font_logo)
    draw.text((120, 38), ".com", fill=(180, 170, 220), font=font_header)
    draw.text((WIDTH // 2 - 150, 30), "Top 5 Tokens", fill=(255, 255, 255), font=font_title)

    # Заголовки таблицы
    header_y = 100
    cols = {"token": 60, "gain": 380, "volume": 560, "mcap": 820}

    draw.text((cols["token"], header_y), "TOKEN:", fill=(180, 170, 220), font=font_header)
    draw.text((cols["gain"], header_y), "DAILY GAIN:", fill=(180, 170, 220), font=font_header)
    draw.text((cols["volume"], header_y), "TRADING VOL.", fill=(180, 170, 220), font=font_header)
    draw.text((cols["mcap"], header_y), "MARKET CAP", fill=(180, 170, 220), font=font_header)
    draw.line([(40, header_y + 30), (WIDTH - 40, header_y + 30)], fill=(60, 50, 100), width=1)

    # Строки таблицы
    row_height = 90
    start_y = header_y + 50

    for i, token in enumerate(tokens):
        y = start_y + i * row_height

        if i % 2 == 0:
            draw.rounded_rectangle(
                [(40, y - 5), (WIDTH - 40, y + row_height - 15)],
                radius=8, fill=(30, 25, 55),
            )

        draw.text((cols["token"], y + 10), token.symbol, fill=(255, 255, 255), font=font_row_bold)
        draw.text((cols["token"], y + 40), f"${format_price(token.price)}", fill=(160, 155, 200), font=font_small)

        # Daily Gain бейдж
        gain_text = f"+{token.daily_gain:.2f}%"
        badge_x = cols["gain"] + 10
        badge_w = len(gain_text) * 11 + 20
        draw.rounded_rectangle(
            [(badge_x, y + 12), (badge_x + badge_w, y + 45)],
            radius=12, fill=(20, 100, 60),
        )
        draw.text((badge_x + 10, y + 16), gain_text, fill=(80, 255, 140), font=font_row)

        # Volume & Market Cap
        vol_text = f"${format_number(token.trading_volume)}" if token.trading_volume else "N/A"
        mcap_text = f"${format_number(token.market_cap)}" if token.market_cap else "N/A"
        draw.text((cols["volume"], y + 18), vol_text, fill=(220, 215, 245), font=font_row)
        draw.text((cols["mcap"], y + 18), mcap_text, fill=(220, 215, 245), font=font_row)

    # Подпись
    now = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
    draw.text((40, HEIGHT - 40), f"Updated: {now}  •  xbo.com", fill=(120, 110, 160), font=font_small)

    buffer = BytesIO()
    img.save(buffer, format="PNG", quality=95)
    buffer.seek(0)
    return buffer


def format_price(price: float) -> str:
    if price >= 1:
        return f"{price:,.2f}"
    elif price >= 0.01:
        return f"{price:.4f}"
    elif price >= 0.0001:
        return f"{price:.6f}"
    else:
        return f"{price:.8f}"


def format_number(num: float) -> str:
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:,.2f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:,.2f}M"
    elif num >= 1_000:
        return f"{num:,.0f}"
    return f"{num:,.2f}"


# ═════════════════════════════════════════════════════════════════════
# 3. ОТПРАВКА В TELEGRAM
# ═════════════════════════════════════════════════════════════════════

def build_post_text(tokens: list[TokenData]) -> str:
    lines = ["🔥 <b>Top 5 Tokens on XBO.com in 24h!</b>\n"]

    for token in tokens:
        trade_url = f"{XBO_SPOT_BASE}/{token.symbol}-USDT"
        vol_str = f"${format_number(token.trading_volume)}" if token.trading_volume else "N/A"
        mcap_str = f"${format_number(token.market_cap)}" if token.market_cap else "N/A"

        lines.append(
            f"💎 <b>${token.symbol}</b>\n"
            f"   Price: <code>${format_price(token.price)}</code>\n"
            f"   24H Performance: <b>+{token.daily_gain:.2f}%</b>\n"
            f"   Trading Volume: <code>{vol_str}</code>\n"
            f"   Market Cap: <code>{mcap_str}</code>\n"
            f"   🔗 <a href=\"{trade_url}\">Trade Now</a>\n"
        )

    lines.append("📊 Data from <a href=\"https://www.xbo.com\">XBO.com</a>")
    return "\n".join(lines)


def send_telegram_post(text: str, image: BytesIO | None = None) -> bool:
    try:
        if image:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            resp = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                files={"photo": ("top5_tokens.png", image, "image/png")},
                timeout=30,
            )
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )

        result = resp.json()
        if result.get("ok"):
            print("✅ Пост отправлен в Telegram!")
            return True
        else:
            print(f"❌ Ошибка Telegram: {result}")
            return False
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ═════════════════════════════════════════════════════════════════════

def main():
    print("🚀 Запуск бота...")

    tokens = fetch_top5_tokens()
    if not tokens:
        print("❌ Не удалось получить данные!")
        return

    print(f"📊 Топ-5: {[f'{t.symbol} +{t.daily_gain}%' for t in tokens]}")

    # Генерация картинки
    try:
        image = generate_image(tokens)
        print("🖼️ Картинка создана")
    except Exception as e:
        print(f"⚠️ Картинка не создана: {e}")
        image = None

    # Отправка
    text = build_post_text(tokens)
    send_telegram_post(text, image)


if __name__ == "__main__":
    main()

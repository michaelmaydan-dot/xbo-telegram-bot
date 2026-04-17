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


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
XBO_SPOT_BASE = "https://www.xbo.com/platform/spot"
XBO_API_BASE = "https://api.xbo.com"


@dataclass
class TokenData:
    symbol: str
    price: float
    daily_gain: float
    trading_volume: float
    market_cap: float


def fetch_top5_tokens() -> list[TokenData]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # Все возможные пути XBO Public API
    paths = [
        "/trading-pairs/stats",
        "/trading-pairs",
        "/trading-pairs-stats",
        "/v1/trading-pairs/stats",
        "/v1/trading-pairs",
        "/tickers",
        "/v1/tickers",
    ]

    for path in paths:
        try:
            url = f"{XBO_API_BASE}{path}"
            print(f"Пробуем: {url}")
            resp = requests.get(url, headers=headers, timeout=15)
            print(f"  Статус: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                preview = json.dumps(data, default=str)[:500]
                print(f"  Данные: {preview}")
                tokens = parse_any_format(data)
                if tokens:
                    print(f"✅ Успех: {path}")
                    return tokens
                else:
                    print(f"  Парсинг не дал результатов")
        except Exception as e:
            print(f"  Ошибка: {e}")

    # Fallback: CoinGecko
    print("\nПробуем CoinGecko...")
    return fetch_via_coingecko()


def parse_any_format(data) -> list[TokenData]:
    tokens = []

    # Определяем формат
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Ищем массив внутри dict
        for key in ["data", "result", "tickers", "pairs"]:
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            # Может быть dict вида {"BTC/USDT": {...}, ...}
            items = []
            for k, v in data.items():
                if isinstance(v, dict):
                    v["_key"] = k
                    items.append(v)
    else:
        return []

    for item in items:
        try:
            if not isinstance(item, dict):
                continue

            # Определяем символ и фильтруем только USDT пары
            symbol_raw = item.get("symbol", item.get("name", item.get("pair", item.get("_key", ""))))
            base = item.get("baseCurrency", item.get("base", ""))
            quote = item.get("quoteCurrency", item.get("target", item.get("quote", "")))

            if quote and quote.upper() == "USDT":
                symbol = base.upper()
            elif "USDT" in str(symbol_raw).upper():
                symbol = str(symbol_raw).upper()
                for suffix in ["/USDT", "_USDT", "-USDT", "USDT"]:
                    symbol = symbol.replace(suffix, "")
                symbol = symbol.strip()
            else:
                continue

            if not symbol or len(symbol) > 15:
                continue

            # Цена
            price = 0
            for key in ["lastPrice", "last", "close", "price", "c"]:
                if key in item:
                    price = float(item[key])
                    break
            # Также пробуем вложенный ticker
            ticker = item.get("ticker", {})
            if not price and isinstance(ticker, dict):
                for key in ["last", "lastPrice", "close"]:
                    if key in ticker:
                        price = float(ticker[key])
                        break

            if price <= 0:
                continue

            # 24h change (%)
            change = None
            for key in ["priceChange24h", "change", "priceChangePercent", "percentagePriceChange", "P"]:
                val = item.get(key, ticker.get(key) if isinstance(ticker, dict) else None)
                if val is not None:
                    change = float(val)
                    break

            if change is None:
                open_p = 0
                for key in ["open", "openPrice"]:
                    val = item.get(key, ticker.get(key) if isinstance(ticker, dict) else None)
                    if val is not None:
                        open_p = float(val)
                        break
                if open_p > 0:
                    change = ((price - open_p) / open_p) * 100
                else:
                    continue

            # Если change в дробном формате (0.05 вместо 5%)
            if abs(change) < 0.5 and change != 0:
                change *= 100

            if change <= 0:
                continue

            # Volume
            volume = 0
            for key in ["quoteVolume", "last24HTradeVolume", "volume", "deal", "vol"]:
                val = item.get(key, ticker.get(key) if isinstance(ticker, dict) else None)
                if val is not None:
                    volume = float(val)
                    break

            mcap = float(item.get("marketCap", 0))

            tokens.append(TokenData(
                symbol=symbol,
                price=price,
                daily_gain=round(change, 2),
                trading_volume=volume,
                market_cap=mcap,
            ))
        except (ValueError, TypeError):
            continue

    tokens.sort(key=lambda t: t.daily_gain, reverse=True)
    return tokens[:5]


def fetch_via_coingecko() -> list[TokenData]:
    try:
        for ex_id in ["xbo-com", "xbo", "xbo_com"]:
            url = f"https://api.coingecko.com/api/v3/exchanges/{ex_id}/tickers"
            print(f"  CoinGecko: {url}")
            resp = requests.get(url, timeout=15)
            print(f"  Статус: {resp.status_code}")
            if resp.status_code != 200:
                continue

            tickers = resp.json().get("tickers", [])
            if not tickers:
                continue

            # Собираем уникальные USDT пары
            token_map = {}
            for t in tickers:
                if t.get("target") != "USDT":
                    continue
                base = t.get("base", "")
                if base not in token_map:
                    token_map[base] = TokenData(
                        symbol=base,
                        price=float(t.get("last", 0)),
                        daily_gain=0,
                        trading_volume=float(t.get("converted_volume", {}).get("usd", 0)),
                        market_cap=0,
                    )

            if not token_map:
                continue

            # Обогащаем 24h change
            enrich_coingecko(token_map)
            tokens = [t for t in token_map.values() if t.daily_gain > 0]
            tokens.sort(key=lambda t: t.daily_gain, reverse=True)
            if tokens:
                print(f"✅ CoinGecko ({ex_id}): {len(tokens)} токенов")
                return tokens[:5]

        return []
    except Exception as e:
        print(f"  CoinGecko ошибка: {e}")
        return []


def enrich_coingecko(token_map: dict):
    try:
        coins = requests.get("https://api.coingecko.com/api/v3/coins/list", timeout=15).json()
        sym_to_id = {}
        for c in coins:
            s = c["symbol"].upper()
            if s not in sym_to_id:
                sym_to_id[s] = c["id"]

        ids, id_to_sym = [], {}
        for sym in token_map:
            cg_id = sym_to_id.get(sym.upper())
            if cg_id:
                ids.append(cg_id)
                id_to_sym[cg_id] = sym

        if not ids:
            return

        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            resp = requests.get(
                f"https://api.coingecko.com/api/v3/coins/markets"
                f"?vs_currency=usd&ids={','.join(chunk)}&price_change_percentage=24h",
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for coin in resp.json():
                sym = id_to_sym.get(coin["id"])
                if sym and sym in token_map:
                    token_map[sym].daily_gain = round(float(coin.get("price_change_percentage_24h") or 0), 2)
                    token_map[sym].market_cap = float(coin.get("market_cap") or 0)
    except Exception as e:
        print(f"  Enrich ошибка: {e}")


# ═════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КАРТИНКИ
# ═════════════════════════════════════════════════════════════════════

def generate_image(tokens: list[TokenData]) -> BytesIO:
    from PIL import Image, ImageDraw, ImageFont

    WIDTH, HEIGHT = 1200, 720
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        r = int(15 + 10 * y / HEIGHT)
        g = int(10 + 8 * y / HEIGHT)
        b = int(40 + 20 * y / HEIGHT)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    for i in range(150):
        a = max(0, 30 - i // 5)
        draw.ellipse([WIDTH - 200 - i, -100 - i, WIDTH + i, 200 + i],
                     fill=(80 + a, 50, 180 + min(a, 75)))

    try:
        fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        fn = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ft = ImageFont.truetype(fb, 42)
        fh = ImageFont.truetype(fb, 18)
        fr = ImageFont.truetype(fn, 20)
        frb = ImageFont.truetype(fb, 20)
        fs = ImageFont.truetype(fn, 14)
        fl = ImageFont.truetype(fb, 36)
    except OSError:
        ft = fh = fr = frb = fs = fl = ImageFont.load_default()

    draw.text((40, 30), "xbo", fill=(120, 90, 255), font=fl)
    draw.text((120, 38), ".com", fill=(180, 170, 220), font=fh)
    draw.text((WIDTH // 2 - 150, 30), "Top 5 Tokens", fill=(255, 255, 255), font=ft)

    hy = 100
    cx = {"t": 60, "g": 380, "v": 560, "m": 820}
    draw.text((cx["t"], hy), "TOKEN:", fill=(180, 170, 220), font=fh)
    draw.text((cx["g"], hy), "DAILY GAIN:", fill=(180, 170, 220), font=fh)
    draw.text((cx["v"], hy), "TRADING VOL.", fill=(180, 170, 220), font=fh)
    draw.text((cx["m"], hy), "MARKET CAP", fill=(180, 170, 220), font=fh)
    draw.line([(40, hy + 30), (WIDTH - 40, hy + 30)], fill=(60, 50, 100), width=1)

    rh, sy = 90, hy + 50
    for i, t in enumerate(tokens):
        y = sy + i * rh
        if i % 2 == 0:
            draw.rounded_rectangle([(40, y - 5), (WIDTH - 40, y + rh - 15)], radius=8, fill=(30, 25, 55))
        draw.text((cx["t"], y + 10), t.symbol, fill=(255, 255, 255), font=frb)
        draw.text((cx["t"], y + 40), f"${format_price(t.price)}", fill=(160, 155, 200), font=fs)
        gt = f"+{t.daily_gain:.2f}%"
        bx = cx["g"] + 10
        bw = len(gt) * 11 + 20
        draw.rounded_rectangle([(bx, y + 12), (bx + bw, y + 45)], radius=12, fill=(20, 100, 60))
        draw.text((bx + 10, y + 16), gt, fill=(80, 255, 140), font=fr)
        draw.text((cx["v"], y + 18), f"${format_number(t.trading_volume)}" if t.trading_volume else "N/A", fill=(220, 215, 245), font=fr)
        draw.text((cx["m"], y + 18), f"${format_number(t.market_cap)}" if t.market_cap else "N/A", fill=(220, 215, 245), font=fr)

    now = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
    draw.text((40, HEIGHT - 40), f"Updated: {now}  •  xbo.com", fill=(120, 110, 160), font=fs)

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def format_price(p):
    if p >= 1: return f"{p:,.2f}"
    elif p >= 0.01: return f"{p:.4f}"
    elif p >= 0.0001: return f"{p:.6f}"
    else: return f"{p:.8f}"


def format_number(n):
    if n >= 1e9: return f"{n/1e9:,.2f}B"
    elif n >= 1e6: return f"{n/1e6:,.2f}M"
    elif n >= 1e3: return f"{n:,.0f}"
    return f"{n:,.2f}"


# ═════════════════════════════════════════════════════════════════════
# ОТПРАВКА В TELEGRAM
# ═════════════════════════════════════════════════════════════════════

def build_post_text(tokens):
    lines = ["🔥 <b>Top 5 Tokens on XBO.com in 24h!</b>\n"]
    for t in tokens:
        url = f"{XBO_SPOT_BASE}/{t.symbol}-USDT"
        v = f"${format_number(t.trading_volume)}" if t.trading_volume else "N/A"
        m = f"${format_number(t.market_cap)}" if t.market_cap else "N/A"
        lines.append(
            f"💎 <b>${t.symbol}</b>\n"
            f"   Price: <code>${format_price(t.price)}</code>\n"
            f"   24H Performance: <b>+{t.daily_gain:.2f}%</b>\n"
            f"   Trading Volume: <code>{v}</code>\n"
            f"   Market Cap: <code>{m}</code>\n"
            f"   🔗 <a href=\"{url}\">Trade Now</a>\n"
        )
    lines.append("📊 Data from <a href=\"https://www.xbo.com\">XBO.com</a>")
    return "\n".join(lines)


def send_telegram(text, image=None):
    try:
        if image:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": text, "parse_mode": "HTML"},
                files={"photo": ("top5.png", image, "image/png")}, timeout=30)
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=30)
        res = r.json()
        if res.get("ok"):
            print("✅ Отправлено в Telegram!")
            return True
        print(f"❌ Telegram: {res}")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def main():
    print("🚀 XBO Top 5 Tokens Bot")
    print(f"   {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")

    tokens = fetch_top5_tokens()
    if not tokens:
        print("\n❌ Данные не получены!")
        exit(1)

    print(f"\n📊 Результат:")
    for t in tokens:
        print(f"   {t.symbol}: ${format_price(t.price)} | +{t.daily_gain}%")

    try:
        image = generate_image(tokens)
        print("🖼️ Картинка готова")
    except Exception as e:
        print(f"⚠️ Без картинки: {e}")
        image = None

    text = build_post_text(tokens)
    if not send_telegram(text, image):
        exit(1)


if __name__ == "__main__":
    main()

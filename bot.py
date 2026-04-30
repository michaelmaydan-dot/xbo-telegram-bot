"""
XBO.com Top 5 Tokens — Telegram Bot (GitHub Actions)
"""

import os
import json
import re
import time
import requests
from datetime import datetime, timezone
from io import BytesIO
from dataclasses import dataclass

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
XBO_SPOT_BASE = "https://www.xbo.com/platform/spot"
XBO_API_BASE = "https://api.xbo.com"
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.png")


@dataclass
class TokenData:
    symbol: str
    price: float
    daily_gain: float
    trading_volume: float
    market_cap: float


def fetch_from_website() -> list[TokenData]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except ImportError:
        print("⚠️ Selenium не установлен")
        return []

    print("🌐 Открываем xbo.com/platform/home...")

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"⚠️ Chrome не запустился: {e}")
        return []

    tokens = []
    try:
        driver.get("https://www.xbo.com/platform/home")
        time.sleep(8)

        try:
            sort_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '24H changes') or contains(text(), '24H change')]")
            if sort_buttons:
                sort_buttons[0].click()
                time.sleep(2)
                print("  Кликнули на сортировку по 24H changes")
        except:
            pass

        rows_data = driver.execute_script(r"""
            const results = [];
            const rows = document.querySelectorAll('tr, [class*="row"], [class*="Row"], [class*="item"], [class*="Item"], [class*="coin"], [class*="Coin"]');
            for (const row of rows) {
                const text = row.textContent || '';
                const changeMatch = text.match(/[+-]?\d+\.?\d*%/);
                if (!changeMatch) continue;
                const change = parseFloat(changeMatch[0].replace('%', ''));
                if (isNaN(change) || change <= 0) continue;
                const allNumbers = [];
                const numRegex = /\$?\s*(\d[\d,]*\.?\d*)\s*([BMK])?/g;
                let match;
                while ((match = numRegex.exec(text)) !== null) {
                    let num = parseFloat(match[1].replace(/,/g, ''));
                    const suffix = match[2];
                    if (suffix === 'B') num *= 1e9;
                    else if (suffix === 'M') num *= 1e6;
                    else if (suffix === 'K') num *= 1e3;
                    allNumbers.push(num);
                }
                const symbolMatch = text.match(/^[^\d]*?\b([A-Z][A-Z0-9]{1,9})\b/);
                let symbol = symbolMatch ? symbolMatch[1] : '';
                const symbolEl = row.querySelector('[class*="symbol"], [class*="Symbol"], [class*="name"], [class*="Name"], [class*="ticker"], [class*="Ticker"]');
                if (symbolEl && !symbol) {
                    const symText = symbolEl.textContent.trim();
                    const symMatch = symText.match(/^([A-Z][A-Z0-9]{1,9})/);
                    if (symMatch) symbol = symMatch[1];
                }
                if (symbol && allNumbers.length >= 1) {
                    results.push({symbol: symbol, change: change, numbers: allNumbers});
                }
            }
            return JSON.stringify(results);
        """)

        if rows_data:
            parsed = json.loads(rows_data)
            for row in parsed:
                sym = row.get("symbol", "")
                change = row.get("change", 0)
                nums = row.get("numbers", [])
                if not sym or change <= 0 or len(nums) < 1:
                    continue
                price = nums[0] if nums else 0
                remaining = []
                change_skipped = False
                for n in nums[1:]:
                    if not change_skipped and abs(n - change) < 0.5:
                        change_skipped = True
                        continue
                    remaining.append(n)
                volume = remaining[0] if len(remaining) > 0 else 0
                mcap = remaining[1] if len(remaining) > 1 else 0
                if price > 0:
                    tokens.append(TokenData(symbol=sym, price=price, daily_gain=round(change, 2),
                                            trading_volume=volume, market_cap=mcap))
    except Exception as e:
        print(f"  Ошибка Selenium: {e}")
    finally:
        driver.quit()

    if tokens:
        tokens.sort(key=lambda t: t.daily_gain, reverse=True)
        return tokens[:5]
    return []


def fetch_from_api() -> list[TokenData]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        url = f"{XBO_API_BASE}/trading-pairs/stats"
        print(f"📡 API: {url}")
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []

        tokens = []
        for item in data:
            try:
                if item.get("quoteCurrency", "").upper() != "USDT":
                    continue
                symbol = item.get("baseCurrency", "").upper()
                price = float(item.get("lastPrice", 0))
                change = float(item.get("priceChangePercent24H", 0))
                volume_usd = float(item.get("last24HTradeVolumeUsd", item.get("quoteVolume", 0)))
                if not symbol or price <= 0 or change <= 0:
                    continue
                tokens.append(TokenData(symbol=symbol, price=price, daily_gain=round(change, 2),
                                        trading_volume=volume_usd, market_cap=0))
            except (ValueError, TypeError):
                continue

        tokens = [t for t in tokens if t.trading_volume > 100]
        tokens.sort(key=lambda t: t.daily_gain, reverse=True)
        top_candidates = tokens[:20]
        if top_candidates:
            enrich_with_coingecko(top_candidates)
            liquid = [t for t in top_candidates if t.trading_volume >= 5_000_000]
            if len(liquid) >= 5:
                return liquid[:5]
            liquid = [t for t in top_candidates if t.trading_volume >= 1_000_000]
            if len(liquid) >= 5:
                return liquid[:5]
            return top_candidates[:5]
        return tokens[:5]
    except Exception as e:
        print(f"  API ошибка: {e}")
        return []


def enrich_with_coingecko(tokens: list[TokenData]):
    try:
        coins = requests.get("https://api.coingecko.com/api/v3/coins/list", timeout=15).json()
        sym_to_id = {}
        for c in coins:
            s = c["symbol"].upper()
            if s not in sym_to_id:
                sym_to_id[s] = c["id"]
        ids, id_to_token = [], {}
        for t in tokens:
            cg_id = sym_to_id.get(t.symbol)
            if cg_id:
                ids.append(cg_id)
                id_to_token[cg_id] = t
        if not ids:
            return
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(ids[:50])}",
            timeout=15)
        if resp.status_code == 200:
            for coin in resp.json():
                t = id_to_token.get(coin["id"])
                if t:
                    t.market_cap = float(coin.get("market_cap") or 0)
                    t.trading_volume = float(coin.get("total_volume") or 0)
    except Exception as e:
        print(f"  CoinGecko ошибка: {e}")


def fetch_top5_tokens() -> list[TokenData]:
    tokens = fetch_from_website()
    if tokens and len(tokens) >= 5:
        print(f"✅ Данные со страницы ({len(tokens)} токенов)")
        return tokens
    print("\n📡 Пробуем API...")
    tokens = fetch_from_api()
    if tokens:
        print(f"✅ Данные из API ({len(tokens)} токенов)")
        return tokens
    return []


def generate_image(tokens: list[TokenData]) -> BytesIO:
    from PIL import Image, ImageDraw, ImageFont

    DEBUG = True  # ⚠️ красные точки. Поставить False когда настроено идеально.

    img = Image.open(TEMPLATE_PATH).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    print(f"   📐 Размер шаблона: {W}x{H}")

    # Точные координаты центров капсул для 640x360 (измерены в Paint)
    sx = W / 640
    sy = H / 360

    try:
        fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        fn = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        f_symbol = ImageFont.truetype(fb, max(10, int(17 * sy)))
        f_price = ImageFont.truetype(fn, max(9, int(14 * sy)))
        f_gain = ImageFont.truetype(fb, max(10, int(18 * sy)))
        f_num = ImageFont.truetype(fn, max(9, int(14 * sy)))
    except OSError:
        f_symbol = f_price = f_gain = f_num = ImageFont.load_default()

    COL_X = {
        "token": int(142 * sx),
        "gain":  int(291 * sx),
        "vol":   int(407 * sx),
        "mcap":  int(526 * sx),
    }
    ROW_Y = [int(y * sy) for y in (140, 178, 216, 254, 292)]

    print(f"   📍 ROW_Y (px): {ROW_Y}")
    print(f"   📍 COL_X (px): {list(COL_X.values())}")

    def center_text(x, y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw // 2, y - th // 2 - bbox[1]), text, fill=fill, font=font)

    def draw_token_cell(x, y, symbol, price):
        price_text = f"${fmt_price(price)}"
        gap = max(4, int(8 * sx))
        s_bbox = draw.textbbox((0, 0), symbol, font=f_symbol)
        p_bbox = draw.textbbox((0, 0), price_text, font=f_price)
        sw = s_bbox[2] - s_bbox[0]
        pw = p_bbox[2] - p_bbox[0]
        total = sw + gap + pw
        sx_pos = x - total // 2
        sy_pos = y - (s_bbox[3] - s_bbox[1]) // 2 - s_bbox[1]
        py_pos = y - (p_bbox[3] - p_bbox[1]) // 2 - p_bbox[1]
        draw.text((sx_pos, sy_pos), symbol, fill=(255, 255, 255), font=f_symbol)
        draw.text((sx_pos + sw + gap, py_pos), price_text, fill=(210, 200, 225), font=f_price)

    for i, t in enumerate(tokens[:5]):
        y = ROW_Y[i]
        draw_token_cell(COL_X["token"], y, t.symbol, t.price)
        center_text(COL_X["gain"], y, f"{t.daily_gain:.2f}%", f_gain, (0, 230, 180))
        vol = f"${int(t.trading_volume):,}" if t.trading_volume else "N/A"
        mcap = f"${int(t.market_cap):,}" if t.market_cap else "N/A"
        center_text(COL_X["vol"], y, vol, f_num, (230, 225, 245))
        center_text(COL_X["mcap"], y, mcap, f_num, (230, 225, 245))

    if DEBUG:
        r = max(4, int(5 * sx))
        for y in ROW_Y:
            for col_x in COL_X.values():
                draw.ellipse([col_x - r, y - r, col_x + r, y + r], fill=(255, 0, 0))

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def fmt_price(p):
    if p >= 1: return f"{p:,.2f}"
    elif p >= 0.01: return f"{p:.4f}"
    elif p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"


def fmt_num(n):
    if n >= 1e9: return f"{n/1e9:,.2f}B"
    elif n >= 1e6: return f"{n/1e6:,.2f}M"
    elif n >= 1e3: return f"{n:,.0f}"
    return f"{n:,.2f}"


def build_post(tokens):
    lines = ["🔥 <b>Top 5 Tokens on XBO.com in 24h!</b>\n"]
    for t in tokens:
        url = f"{XBO_SPOT_BASE}/{t.symbol}-USDT"
        v = f"${fmt_num(t.trading_volume)}" if t.trading_volume else "N/A"
        m = f"${fmt_num(t.market_cap)}" if t.market_cap else "N/A"
        lines.append(
            f"💎 <b>${t.symbol}</b>\n"
            f"   Price: <code>${fmt_price(t.price)}</code>\n"
            f"   24H Performance: <b>+{t.daily_gain:.2f}%</b>\n"
            f"   Trading Volume: <code>{v}</code>\n"
            f"   Market Cap: <code>{m}</code>\n"
            f"   🔗 Trade Now: {url}\n")
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
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    tokens = fetch_top5_tokens()
    if not tokens:
        print("\n❌ Данные не получены!")
        exit(1)
    print(f"\n📊 Топ-5:")
    for t in tokens:
        print(f"   {t.symbol}: ${fmt_price(t.price)} | +{t.daily_gain}% | Vol: ${fmt_num(t.trading_volume)} | MCap: ${fmt_num(t.market_cap)}")
    try:
        image = generate_image(tokens)
        print("🖼️ Картинка готова")
    except Exception as e:
        print(f"⚠️ Без картинки: {e}")
        image = None
    if not send_telegram(build_post(tokens), image):
        exit(1)


if __name__ == "__main__":
    main()

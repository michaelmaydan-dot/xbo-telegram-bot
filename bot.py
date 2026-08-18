"""
XBO.com Top 5 Tokens — Telegram Bot (GitHub Actions)
"""

import os
import json
import re
import math
import time
import requests
from datetime import datetime, timezone
from io import BytesIO
from dataclasses import dataclass, field

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID")
XBO_SPOT_BASE = "https://www.xbo.com/platform/spot"
XBO_API_BASE = "https://api.xbo.com"
XBO_LOGO_CDN = "https://assets.xbo.com/token-icons/png"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "template.png")
TEMPLATE_INSTA_PATH = os.path.join(BASE_DIR, "template_insta.png")
LOGOS_DIR = os.path.join(BASE_DIR, "logos")
FONT_BLACK = os.path.join(BASE_DIR, "fonts", "fonnts.com-Apertura_Black.otf")
FONT_MEDIUM = os.path.join(BASE_DIR, "fonts", "fonnts.com-Apertura_Medium.otf")
FONT_REGULAR = os.path.join(BASE_DIR, "fonts", "fonnts.com-Apertura_Regular.otf")
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@dataclass
class TokenData:
    symbol: str
    price: float
    daily_gain: float
    trading_volume: float
    market_cap: float
    logo_url: str = ""


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
                    tokens.append(TokenData(
                        symbol=sym, price=price, daily_gain=round(change, 2),
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
        coins_list = requests.get("https://api.coingecko.com/api/v3/coins/list", timeout=15).json()
        sym_to_ids = {}
        for c in coins_list:
            s = c["symbol"].upper()
            sym_to_ids.setdefault(s, []).append(c["id"])

        all_ids = []
        for t in tokens:
            for cg_id in sym_to_ids.get(t.symbol, [])[:8]:
                all_ids.append(cg_id)
        if not all_ids:
            return

        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(all_ids[:250])}",
            timeout=15)
        if resp.status_code != 200:
            return

        market_data = resp.json()
        by_symbol = {}
        for coin in market_data:
            s = coin["symbol"].upper()
            by_symbol.setdefault(s, []).append(coin)

        for t in tokens:
            candidates = by_symbol.get(t.symbol, [])
            if not candidates or t.price <= 0:
                continue
            best, best_diff = None, float('inf')
            for c in candidates:
                cg_price = float(c.get("current_price") or 0)
                if cg_price <= 0:
                    continue
                diff = abs(math.log(cg_price / t.price))
                if diff < best_diff:
                    best_diff, best = diff, c
            if best and best_diff < 0.4:
                t.market_cap = float(best.get("market_cap") or 0)
                t.trading_volume = float(best.get("total_volume") or 0)
                if not t.logo_url:
                    t.logo_url = best.get("image") or ""
    except Exception as e:
        print(f"  CoinGecko ошибка: {e}")


def fetch_top5_tokens() -> list[TokenData]:
    tokens = fetch_from_website()
    if tokens and len(tokens) >= 5:
        print(f"✅ Данные со страницы ({len(tokens)} токенов)")
        enrich_with_coingecko(tokens)
        return tokens
    print("\n📡 Пробуем API...")
    tokens = fetch_from_api()
    if tokens:
        print(f"✅ Данные из API ({len(tokens)} токенов)")
        return tokens
    return []


def _load_font(path, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.truetype(FONT_FALLBACK, size)
        except OSError:
            return ImageFont.load_default()


def _trim_transparent(img):
    if img.mode != "RGBA":
        return img
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def _make_circular(logo, size):
    from PIL import Image, ImageDraw
    logo = _trim_transparent(logo)
    w, h = logo.size
    max_dim = max(w, h)
    square = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
    square.paste(logo, ((max_dim - w) // 2, (max_dim - h) // 2))
    square = square.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(square, (0, 0), mask)
    return output


def _create_text_logo(ticker, size):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(120, 120, 130, 255))
    font = _load_font(FONT_BLACK, max(8, int(size * 0.3)))
    text = ticker if len(ticker) <= 5 else ticker[:4]
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - bbox[1]),
              text, fill=(255, 255, 255, 255), font=font)
    return img


def _try_download_logo(url, size):
    from PIL import Image, UnidentifiedImageError
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("image/"):
            return None
        logo = Image.open(BytesIO(r.content)).convert("RGBA")
        return _make_circular(logo, size)
    except (UnidentifiedImageError, OSError, requests.exceptions.RequestException):
        return None


def get_token_logo(token: TokenData, size: int):
    from PIL import Image
    local_path = os.path.join(LOGOS_DIR, f"{token.symbol}.png")
    if os.path.exists(local_path):
        try:
            logo = Image.open(local_path).convert("RGBA")
            print(f"  ✅ Лого {token.symbol}: logos/")
            return _make_circular(logo, size)
        except Exception as e:
            print(f"  ⚠️ logos/{token.symbol}.png не загрузилось: {e}")
    cdn_url = f"{XBO_LOGO_CDN}/{token.symbol}.png"
    cdn_logo = _try_download_logo(cdn_url, size)
    if cdn_logo:
        print(f"  ✅ Лого {token.symbol}: XBO CDN")
        return cdn_logo
    if token.logo_url:
        cg_logo = _try_download_logo(token.logo_url, size)
        if cg_logo:
            print(f"  ✅ Лого {token.symbol}: CoinGecko")
            return cg_logo
    print(f"  ℹ️ Лого {token.symbol} не найдено, серый круг")
    return _create_text_logo(token.symbol, size)


def generate_image_telegram(tokens: list[TokenData]) -> BytesIO:
    """Горизонтальная картинка 640x360 для Telegram."""
    from PIL import Image, ImageDraw

    img = Image.open(TEMPLATE_PATH).convert("RGBA")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    print(f"   📐 Шаблон TG: {W}x{H}")

    f_badge = _load_font(FONT_MEDIUM, 14)
    f_ticker = _load_font(FONT_REGULAR, 20)
    f_price = _load_font(FONT_BLACK, 20)

    CARD_X = [89, 202, 320, 434, 549]
    BADGE_Y = 107
    LOGO_Y = 157
    NAME_Y = 230
    PRICE_Y = 252
    LOGO_SIZE = 50

    def draw_centered(x, y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x - tw // 2, y - th // 2 - bbox[1]), text, fill=fill, font=font)

    for i, t in enumerate(tokens[:5]):
        x = CARD_X[i]
        draw_centered(x, BADGE_Y, f"+{t.daily_gain:.2f}%", f_badge, (255, 255, 255))
        logo = get_token_logo(t, LOGO_SIZE)
        img.paste(logo, (x - LOGO_SIZE // 2, LOGO_Y - LOGO_SIZE // 2), logo)
        draw_centered(x, NAME_Y, t.symbol, f_ticker, (255, 255, 255))
        draw_centered(x, PRICE_Y, f"${fmt_price(t.price)}", f_price, (255, 255, 255))

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def generate_image_insta(tokens: list[TokenData]) -> BytesIO:
    """Вертикальная картинка 1080x1920 для Instagram."""
    from PIL import Image, ImageDraw

    img = Image.open(TEMPLATE_INSTA_PATH).convert("RGBA")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    print(f"   📐 Шаблон Insta: {W}x{H}")

    f_badge = _load_font(FONT_MEDIUM, 32)
    f_ticker = _load_font(FONT_REGULAR, 40)
    f_price = _load_font(FONT_BLACK, 40)

    ROW_Y = [592, 804, 1018, 1232, 1447]
    LOGO_X = 220
    TEXT_X = 376
    BADGE_X = 840
    LOGO_SIZE = 135

    def draw_centered(x, y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x - tw // 2, y - th // 2 - bbox[1]), text, fill=fill, font=font)

    def draw_left(x, y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        th = bbox[3] - bbox[1]
        draw.text((x, y - th // 2 - bbox[1]), text, fill=fill, font=font)
        return bbox[2] - bbox[0]

    for i, t in enumerate(tokens[:5]):
        y = ROW_Y[i]
        logo = get_token_logo(t, LOGO_SIZE)
        img.paste(logo, (LOGO_X - LOGO_SIZE // 2, y - LOGO_SIZE // 2), logo)
        ticker_w = draw_left(TEXT_X, y, t.symbol, f_ticker, (255, 255, 255))
        draw_left(TEXT_X + ticker_w + 15, y, f"${fmt_price(t.price)}", f_price, (255, 255, 255))
        draw_centered(BADGE_X, y, f"+{t.daily_gain:.2f}%", f_badge, (255, 255, 255))

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
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
    lines = ["🔝 <b>Top 5 Movers on XBO.com in 24h</b> 📊\n"]
    for t in tokens:
        url = f"{XBO_SPOT_BASE}/{t.symbol}-USDT"
        display = f"xbo.com/platform/spot/{t.symbol}-USDT"
        lines.append(
            f"🟢 <b>${t.symbol}</b> | <b>${fmt_price(t.price)}</b> | <b>+{t.daily_gain:.2f}%</b>\n"
            f'🔗 Trade Now: <a href="{url}">{display}</a>\n')
    lines.append('\n👉 <a href="https://www.xbo.com/platform/spot">xbo.com/platform/spot</a> 🔗')
    return "\n".join(lines)


def _resolve_thread_id():
    if not TELEGRAM_THREAD_ID:
        return None
    try:
        return int(TELEGRAM_THREAD_ID)
    except ValueError:
        print(f"⚠️ TELEGRAM_THREAD_ID не число: '{TELEGRAM_THREAD_ID}', игнорируем")
        return None


def send_telegram(text, image_tg=None, image_insta=None):
    try:
        thread_id = _resolve_thread_id()
        base_data = {"chat_id": TELEGRAM_CHAT_ID}
        if thread_id is not None:
            base_data["message_thread_id"] = thread_id

        # 1. Отправляем картинку для Telegram (с текстом если влезает)
        if image_tg:
            if len(text) <= 1024:
                data = {**base_data, "caption": text, "parse_mode": "HTML"}
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data=data,
                    files={"photo": ("top5_tg.png", image_tg, "image/png")}, timeout=30)
                res = r.json()
                if not res.get("ok"):
                    print(f"❌ sendPhoto TG: {res.get('description')}")
                    return False
            else:
                # Фото отдельно, текст отдельно
                r1 = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data=base_data,
                    files={"photo": ("top5_tg.png", image_tg, "image/png")}, timeout=30)
                if not r1.json().get("ok"):
                    print(f"❌ sendPhoto TG: {r1.json().get('description')}")
                    return False
                payload = {**base_data, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}
                r2 = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json=payload, timeout=30)
                if not r2.json().get("ok"):
                    print(f"❌ sendMessage: {r2.json().get('description')}")
                    return False
        else:
            payload = {**base_data, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload, timeout=30)
            if not r.json().get("ok"):
                print(f"❌ sendMessage: {r.json().get('description')}")
                return False

        # 2. Отправляем картинку для Instagram (как отдельное фото)
        if image_insta:
            r3 = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data=base_data,
                files={"photo": ("top5_insta.png", image_insta, "image/png")}, timeout=30)
            if r3.json().get("ok"):
                print("✅ Insta-картинка отправлена")
            else:
                print(f"⚠️ Insta-картинка не отправлена: {r3.json().get('description')}")

        print("✅ Отправлено в Telegram!")
        return True
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
        print(f"   {t.symbol}: ${fmt_price(t.price)} | +{t.daily_gain}%")

    # Генерация картинки для Telegram (640x360)
    image_tg = None
    try:
        image_tg = generate_image_telegram(tokens)
        print("🖼️ TG-картинка готова")
    except Exception as e:
        print(f"⚠️ TG-картинка не создана: {e}")

    # Генерация картинки для Instagram (1080x1920)
    image_insta = None
    try:
        image_insta = generate_image_insta(tokens)
        print("🖼️ Insta-картинка готова")
    except Exception as e:
        print(f"⚠️ Insta-картинка не создана: {e}")

    if not send_telegram(build_post(tokens), image_tg, image_insta):
        exit(1)


if __name__ == "__main__":
    main()

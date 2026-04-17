"""
XBO.com Top 5 Tokens — Telegram Bot (GitHub Actions)
Парсит топ-5 растущих токенов со страницы xbo.com/platform/home
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


@dataclass
class TokenData:
    symbol: str
    price: float
    daily_gain: float
    trading_volume: float
    market_cap: float


# ═════════════════════════════════════════════════════════════════════
# 1. ПАРСИНГ СТРАНИЦЫ XBO.COM (Selenium)
# ═════════════════════════════════════════════════════════════════════

def fetch_from_website() -> list[TokenData]:
    """Парсим страницу xbo.com/platform/home через Selenium."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
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
        time.sleep(8)  # Ждём загрузки SPA

        # Способ 1: Перехватываем API-запросы из Network
        # Ищем данные в JavaScript переменных страницы
        try:
            page_data = driver.execute_script("""
                // Ищем данные в разных местах
                if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
                if (window.__NUXT__) return JSON.stringify(window.__NUXT__);
                if (window.__APP_DATA__) return JSON.stringify(window.__APP_DATA__);
                return null;
            """)
            if page_data:
                print(f"  Найдены данные в window (длина: {len(page_data)})")
        except:
            pass

        # Способ 2: Парсим таблицу со страницы
        print("  Парсим таблицу...")
        time.sleep(3)

        # Пробуем кликнуть на сортировку по 24H changes чтобы получить top gainers
        try:
            sort_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '24H changes') or contains(text(), '24H change')]")
            if sort_buttons:
                sort_buttons[0].click()
                time.sleep(2)
                print("  Кликнули на сортировку по 24H changes")
        except:
            pass

        # Извлекаем данные из таблицы
        rows_data = driver.execute_script("""
            const results = [];

            // Ищем все строки таблицы/списка
            const rows = document.querySelectorAll('tr, [class*="row"], [class*="Row"], [class*="item"], [class*="Item"], [class*="coin"], [class*="Coin"]');

            for (const row of rows) {
                const text = row.textContent || '';

                // Ищем паттерн: символ, цена, процент изменения, объём, маркет кеп
                // Пример: "PNUT Peanut the Squirrel 0.0691 +25.58% $ 319.80M $ 67.64M"

                // Извлекаем процент изменения
                const changeMatch = text.match(/[+-]?\d+\.?\d*%/);
                if (!changeMatch) continue;

                const change = parseFloat(changeMatch[0].replace('%', ''));
                if (isNaN(change) || change <= 0) continue;

                // Извлекаем все числа с $ или без
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

                // Ищем символ токена (обычно большие буквы, 2-10 символов)
                const symbolMatch = text.match(/^[^\\d]*?\\b([A-Z][A-Z0-9]{1,9})\\b/);
                let symbol = symbolMatch ? symbolMatch[1] : '';

                // Также пробуем найти через элементы
                const symbolEl = row.querySelector('[class*="symbol"], [class*="Symbol"], [class*="name"], [class*="Name"], [class*="ticker"], [class*="Ticker"]');
                if (symbolEl && !symbol) {
                    const symText = symbolEl.textContent.trim();
                    const symMatch = symText.match(/^([A-Z][A-Z0-9]{1,9})/);
                    if (symMatch) symbol = symMatch[1];
                }

                if (symbol && allNumbers.length >= 1) {
                    results.push({
                        symbol: symbol,
                        text: text.substring(0, 200),
                        change: change,
                        numbers: allNumbers
                    });
                }
            }

            return JSON.stringify(results);
        """)

        if rows_data:
            parsed = json.loads(rows_data)
            print(f"  Найдено строк с данными: {len(parsed)}")
            for row in parsed[:15]:  # Логируем первые 15
                print(f"    {row.get('symbol', '?')}: change={row.get('change')}%, numbers={row.get('numbers', [])[:5]}")

            for row in parsed:
                sym = row.get("symbol", "")
                change = row.get("change", 0)
                nums = row.get("numbers", [])

                if not sym or change <= 0 or len(nums) < 1:
                    continue

                # Определяем поля: обычно price, volume, market_cap
                price = nums[0] if nums else 0
                volume = nums[1] if len(nums) > 1 else 0
                mcap = nums[2] if len(nums) > 2 else 0

                if price > 0:
                    tokens.append(TokenData(
                        symbol=sym,
                        price=price,
                        daily_gain=round(change, 2),
                        trading_volume=volume,
                        market_cap=mcap,
                    ))

        # Способ 3: Перехватываем XHR запросы
        if not tokens:
            print("  Пробуем перехватить XHR...")
            logs = driver.execute_script("""
                const entries = performance.getEntriesByType('resource');
                return entries
                    .filter(e => e.name.includes('api') || e.name.includes('ticker') || e.name.includes('market'))
                    .map(e => e.name);
            """)
            if logs:
                print(f"  API запросы страницы: {logs[:10]}")

    except Exception as e:
        print(f"  Ошибка Selenium: {e}")
    finally:
        driver.quit()

    if tokens:
        tokens.sort(key=lambda t: t.daily_gain, reverse=True)
        return tokens[:5]
    return []


# ═════════════════════════════════════════════════════════════════════
# 2. XBO API + ФИЛЬТРАЦИЯ (fallback)
# ═════════════════════════════════════════════════════════════════════

def fetch_from_api() -> list[TokenData]:
    """XBO API /trading-pairs/stats с фильтрацией по ликвидности."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    try:
        url = f"{XBO_API_BASE}/trading-pairs/stats"
        print(f"📡 API: {url}")
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            print(f"  Статус: {resp.status_code}")
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []

        print(f"  Получено пар: {len(data)}")

        tokens = []
        for item in data:
            try:
                quote = item.get("quoteCurrency", "").upper()
                if quote != "USDT":
                    continue

                symbol = item.get("baseCurrency", "").upper()
                price = float(item.get("lastPrice", 0))
                change = float(item.get("priceChangePercent24H", 0))
                volume_usd = float(item.get("last24HTradeVolumeUsd", item.get("quoteVolume", 0)))

                if not symbol or price <= 0 or change <= 0:
                    continue

                tokens.append(TokenData(
                    symbol=symbol,
                    price=price,
                    daily_gain=round(change, 2),
                    trading_volume=volume_usd,
                    market_cap=0,
                ))
            except (ValueError, TypeError):
                continue

        print(f"  Пар с ростом: {len(tokens)}")

        # Фильтруем как сайт XBO: только монеты которые показываются на /platform/home
        # Сайт показывает монеты с глобальным объёмом от ~$5M+
        # Используем XBO volume > $100 как минимальный порог (чтобы исключить мертвые пары)
        # и потом обогащаем данными CoinGecko для отбора по глобальному объёму
        tokens = [t for t in tokens if t.trading_volume > 100]
        tokens.sort(key=lambda t: t.daily_gain, reverse=True)

        # Берём топ-20 по росту и обогащаем CoinGecko данными
        top_candidates = tokens[:20]
        if top_candidates:
            enrich_with_coingecko(top_candidates)
            # Фильтруем: только монеты с глобальным Volume >= $5M (как на сайте)
            liquid = [t for t in top_candidates if t.trading_volume >= 5_000_000]
            if len(liquid) >= 5:
                return liquid[:5]
            # Если мало — снижаем порог
            liquid = [t for t in top_candidates if t.trading_volume >= 1_000_000]
            if len(liquid) >= 5:
                return liquid[:5]
            # Совсем fallback
            return top_candidates[:5]

        return tokens[:5]

    except Exception as e:
        print(f"  API ошибка: {e}")
        return []


def enrich_with_coingecko(tokens: list[TokenData]):
    """Подтягиваем глобальный Volume и Market Cap из CoinGecko."""
    try:
        print("  Обогащаем данные из CoinGecko...")
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
            print("  Не удалось сопоставить символы с CoinGecko")
            return

        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&ids={','.join(ids[:50])}",
            timeout=15,
        )
        if resp.status_code == 200:
            for coin in resp.json():
                t = id_to_token.get(coin["id"])
                if t:
                    t.market_cap = float(coin.get("market_cap") or 0)
                    global_vol = float(coin.get("total_volume") or 0)
                    t.trading_volume = global_vol  # Заменяем на глобальный
            print(f"  ✅ CoinGecko: обогащено {len(id_to_token)} монет")
        else:
            print(f"  CoinGecko статус: {resp.status_code}")
    except Exception as e:
        print(f"  CoinGecko ошибка: {e}")


# ═════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ДАННЫХ
# ═════════════════════════════════════════════════════════════════════

def fetch_top5_tokens() -> list[TokenData]:
    # Попытка 1: Selenium (парсинг страницы)
    tokens = fetch_from_website()
    if tokens and len(tokens) >= 5:
        print(f"✅ Данные со страницы xbo.com ({len(tokens)} токенов)")
        return tokens

    # Попытка 2: API + CoinGecko фильтрация
    print("\n📡 Пробуем API...")
    tokens = fetch_from_api()
    if tokens:
        print(f"✅ Данные из API ({len(tokens)} токенов)")
        return tokens

    return []


# ═════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КАРТИНКИ
# ═════════════════════════════════════════════════════════════════════

def generate_image(tokens: list[TokenData]) -> BytesIO:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 720
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    for y in range(H):
        draw.line([(0, y), (W, y)], fill=(
            int(15 + 10 * y / H), int(10 + 8 * y / H), int(40 + 20 * y / H)))

    for i in range(150):
        a = max(0, 30 - i // 5)
        draw.ellipse([W-200-i, -100-i, W+i, 200+i], fill=(80+a, 50, 180+min(a, 75)))

    try:
        fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        fn = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ft, fh, fr, frb, fs, fl = (
            ImageFont.truetype(fb, 42), ImageFont.truetype(fb, 18),
            ImageFont.truetype(fn, 20), ImageFont.truetype(fb, 20),
            ImageFont.truetype(fn, 14), ImageFont.truetype(fb, 36))
    except OSError:
        ft = fh = fr = frb = fs = fl = ImageFont.load_default()

    draw.text((40, 30), "xbo", fill=(120, 90, 255), font=fl)
    draw.text((120, 38), ".com", fill=(180, 170, 220), font=fh)
    draw.text((W//2 - 150, 30), "Top 5 Tokens", fill=(255, 255, 255), font=ft)

    hy = 100
    cx = {"t": 60, "g": 380, "v": 560, "m": 820}
    for label, x in [("TOKEN:", cx["t"]), ("DAILY GAIN:", cx["g"]),
                      ("TRADING VOL.", cx["v"]), ("MARKET CAP", cx["m"])]:
        draw.text((x, hy), label, fill=(180, 170, 220), font=fh)
    draw.line([(40, hy+30), (W-40, hy+30)], fill=(60, 50, 100), width=1)

    for i, t in enumerate(tokens):
        y = hy + 50 + i * 90
        if i % 2 == 0:
            draw.rounded_rectangle([(40, y-5), (W-40, y+75)], radius=8, fill=(30, 25, 55))
        draw.text((cx["t"], y+10), t.symbol, fill=(255, 255, 255), font=frb)
        draw.text((cx["t"], y+40), f"${fmt_price(t.price)}", fill=(160, 155, 200), font=fs)
        gt = f"+{t.daily_gain:.2f}%"
        bx, bw = cx["g"]+10, len(gt)*11+20
        draw.rounded_rectangle([(bx, y+12), (bx+bw, y+45)], radius=12, fill=(20, 100, 60))
        draw.text((bx+10, y+16), gt, fill=(80, 255, 140), font=fr)
        draw.text((cx["v"], y+18), f"${fmt_num(t.trading_volume)}" if t.trading_volume else "N/A", fill=(220, 215, 245), font=fr)
        draw.text((cx["m"], y+18), f"${fmt_num(t.market_cap)}" if t.market_cap else "N/A", fill=(220, 215, 245), font=fr)

    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    draw.text((40, H-40), f"Updated: {now}  •  xbo.com", fill=(120, 110, 160), font=fs)

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


# ═════════════════════════════════════════════════════════════════════
# TELEGRAM
# ═════════════════════════════════════════════════════════════════════

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
            f"   🔗 <a href=\"{url}\">Trade Now</a>\n")
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

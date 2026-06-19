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

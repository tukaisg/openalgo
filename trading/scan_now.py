import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openalgo import api

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
API_KEY = os.getenv("OPENALGO_API_KEY")
HOST = "http://127.0.0.1:5000"
client = api(api_key=API_KEY, host=HOST)

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_future():
    # Quick resolution
    return "NIFTY30DEC25FUT"

import requests

def fetch_candles(symbol):
    url = f"{HOST}/api/v1/history"
    start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    payload = {
        "apikey": API_KEY,
        "symbol": symbol,
        "exchange": "NFO",
        "interval": "1m",
        "start_date": start,
        "end_date": end
    }
    
    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict):
            if isinstance(data.get("data"), list): return data["data"]
            if isinstance(data.get("data"), dict) and isinstance(data["data"].get("candles"), list): return data["data"]["candles"]
    except Exception as e:
        log(f"Fetch Error: {e}")
    return []

def analyze():
    symbol = get_future()
    log(f"Scanning {symbol}...")
    candles = fetch_candles(symbol)
    if not candles:
        log("No data.")
        return

    df = pd.DataFrame(candles)
    df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'}, inplace=True)
    df['close'] = pd.to_numeric(df['close'])
    
    # Indicators
    df['ema'] = df['close'].ewm(span=200, adjust=False).mean()
    
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    k = df['close'].ewm(span=12, adjust=False).mean()
    d = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = k - d
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    last = df.iloc[-1]
    
    log(f"LTP: {last['close']}")
    log(f"EMA(200): {last['ema']:.2f}")
    log(f"RSI(14): {last['rsi']:.2f}")
    log(f"MACD: {last['macd']:.2f} / Sig: {last['signal']:.2f}")
    
    # Check Logic
    # LONG
    if last['close'] > last['ema'] and last['rsi'] < 45 and last['macd'] > last['signal']:
        print("\n🔥 SIGNAL: BUY (LONG CONFLUENCE) 🔥")
    elif last['close'] < last['ema'] and last['rsi'] > 55 and last['macd'] < last['signal']:
        print("\n❄️ SIGNAL: SELL (SHORT CONFLUENCE) ❄️")
    else:
        print("\n✋ NO SIGNAL (NEUTRAL)")
        if last['close'] > last['ema']: print("   - Trend: Bullish (Above EMA)")
        else: print("   - Trend: Bearish (Below EMA)")
        
        if last['rsi'] < 45: print("   - RSI: Oversold (Good for Buy)")
        elif last['rsi'] > 55: print("   - RSI: Overbought (Good for Sell)")
        else: print(f"   - RSI: Neutral ({last['rsi']:.2f})")
        
        if last['macd'] > last['signal']: print("   - MACD: Bullish Cross")
        else: print("   - MACD: Bearish Cross")

if __name__ == "__main__":
    analyze()

import os
import sys
import time
from datetime import datetime, timedelta, date
import calendar
import pandas as pd
import threading
from dotenv import load_dotenv
from openalgo import api

# --- Configuration ---
DRY_RUN = False  # Set to True for testing usage first if desired
IS_HEDGE_STRATEGY = True
SPREAD_WIDTH = 200
SYMBOL_PREFIX = "NIFTY"
EXCHANGE = "NFO"
TIMEFRAME_MINUTES = 1
HISTORY_DAYS = 5 
LOT_SIZE = 75 

# Strategy Parameters
RSI_PERIOD = 14
RSI_OVERBOUGHT = 55
RSI_OVERSOLD = 45 
EMA_PERIOD = 200
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Risk Management (Points)
STOP_LOSS_POINTS = 20
TAKE_PROFIT_POINTS = 50
TSL_ACTIVATION_POINTS = 20
TSL_TRAIL_POINTS = 10

# Time Filters
MORNING_START = "09:15"
MORNING_END = "11:00"
AFTERNOON_START = "13:00"
AFTERNOON_END = "15:00"

# --- Setup ---
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
API_KEY = os.getenv("OPENALGO_API_KEY")
HOST = "http://127.0.0.1:5000"

if not API_KEY:
    print("Error: OPENALGO_API_KEY not found in .env")
    sys.exit(1)

client = api(api_key=API_KEY, host=HOST)

# Global State
current_symbol = None 
traded_long_symbol = None 
traded_short_symbol = None
position = None # None, 'BULL_SPREAD', 'BEAR_SPREAD'
entry_price = 0.0 # Entry Price of FUTURE
stop_loss = 0.0 
take_profit = 0.0 
highest_price = 0.0 
lowest_price = 0.0  

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def get_option_symbol(future_symbol, price, side, offset=0):
    """
    Construct Option Symbol based on Future Symbol.
    offset: 0 for ATM, +200 for OTM Call etc.
    """
    try:
        base = future_symbol.replace("FUT", "")
        strike = round(price / 50) * 50
        
        # Adjust strike for OTM
        # If BUY/Call (Side=BUY), OTM is Higher Strike (+offset)
        # If SELL/Put (Side=SELL), OTM is Lower Strike (-offset)
        
        final_strike = strike
        opt_type = "CE" if side == "BUY" else "PE"
        
        if offset > 0:
            if opt_type == "CE":
                final_strike = strike + offset
            else:
                final_strike = strike - offset
                
        opt_symbol = f"{base}{final_strike}{opt_type}"
        return opt_symbol
    except Exception as e:
        log(f"Option Symbol Construct Error: {e}")
        return None

def place_order(side, price):
    global position, entry_price, stop_loss, take_profit, highest_price, lowest_price
    global traded_long_symbol, traded_short_symbol
    
    # 1. Determine Symbols
    # Side passed is the Strategy Signal (BUY=Long/Bull, SELL=Short/Bear)
    
    atm_sym = get_option_symbol(current_symbol, price, side, offset=0)
    otm_sym = get_option_symbol(current_symbol, price, side, offset=SPREAD_WIDTH)
    
    if not atm_sym or not otm_sym:
        log("ABORT: Could not determine symbols.")
        return

    log(f"[{'DRY RUN' if DRY_RUN else 'LIVE'}] SPREAD ENTRY ({side}): Long {atm_sym} | Short {otm_sym}")

    if DRY_RUN:
        traded_long_symbol = atm_sym
        traded_short_symbol = otm_sym
        position = "BULL_SPREAD" if side == "BUY" else "BEAR_SPREAD"
        entry_price = price 
        
        if side == "BUY":
            stop_loss = entry_price - STOP_LOSS_POINTS
            take_profit = entry_price + TAKE_PROFIT_POINTS
            highest_price = entry_price
        else:
            stop_loss = entry_price + STOP_LOSS_POINTS
            take_profit = entry_price - TAKE_PROFIT_POINTS
            lowest_price = entry_price
        log(f"  -> Sim Position: {position} | Future Entry: {entry_price}")
        return

    # Live Execution - Sequential
    try:
        # Leg 1: Buy ATM
        res1 = client.placeorder(symbol=atm_sym, action="BUY", exchange=EXCHANGE, price_type="MARKET", product="MIS", quantity=LOT_SIZE)
        log(f"Leg 1 (Long) Response: {res1}")
        
        if res1.get('status') == 'success':
            traded_long_symbol = atm_sym
            time.sleep(1) # Small delay
            
            # Leg 2: Sell OTM
            res2 = client.placeorder(symbol=otm_sym, action="SELL", exchange=EXCHANGE, price_type="MARKET", product="MIS", quantity=LOT_SIZE)
            log(f"Leg 2 (Short) Response: {res2}")
            
            if res2.get('status') == 'success':
                traded_short_symbol = otm_sym
                position = "BULL_SPREAD" if side == "BUY" else "BEAR_SPREAD"
                entry_price = price
                
                if side == "BUY":
                    stop_loss = entry_price - STOP_LOSS_POINTS
                    take_profit = entry_price + TAKE_PROFIT_POINTS
                    highest_price = entry_price
                else:
                    stop_loss = entry_price + STOP_LOSS_POINTS
                    take_profit = entry_price - TAKE_PROFIT_POINTS
                    lowest_price = entry_price
                    
                log(f"  -> Spread Executed. State: {position}")
            else:
                log("CRITICAL: Leg 2 Failed! We are Naked Long option tracking logic required.")
                # Fallback: Just track as Bull/Bear Spread but without short leg? 
                # Or close leg 1? 
                # For now, simplistic: Treat as Spread but warn.
                position = "BULL_SPREAD" if side == "BUY" else "BEAR_SPREAD"
                entry_price = price
                # No traded_short_symbol set
        else:
            log(f"Leg 1 Failed: {res1.get('message')}")
            
    except Exception as e:
        log(f"Order Exception: {e}")

def close_position(price, reason):
    global position, entry_price, stop_loss, take_profit, traded_long_symbol, traded_short_symbol
    
    log(f"[{'DRY RUN' if DRY_RUN else 'LIVE'}] Closing Spread ({reason}). Trigger: {price}")
    
    if DRY_RUN:
        log("  -> Sim Position Closed")
    else:
        try:
            # Close Short Leg First (Buy Back)
            if traded_short_symbol:
                res1 = client.placeorder(symbol=traded_short_symbol, action="BUY", exchange=EXCHANGE, price_type="MARKET", product="MIS", quantity=LOT_SIZE)
                log(f"Exit Leg 1 (Short Cover): {res1}")
                time.sleep(1)
            
            # Close Long Leg Second (Sell)
            if traded_long_symbol:
                res2 = client.placeorder(symbol=traded_long_symbol, action="SELL", exchange=EXCHANGE, price_type="MARKET", product="MIS", quantity=LOT_SIZE)
                log(f"Exit Leg 2 (Long Sell): {res2}")
                
        except Exception as e:
            log(f"Exit Exception: {e}")

    position = None
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    traded_long_symbol = None
    traded_short_symbol = None

def resolve_current_symbol():
    """Find the NIFTY Futures symbol."""
    now = datetime.now()
    mmm = now.strftime("%b").upper()
    yy = now.strftime("%y")
    query = f"{SYMBOL_PREFIX} {mmm} {yy}"
    try:
        response = client.search(query=query, exchange=EXCHANGE)
        if isinstance(response, dict) and response.get('status') == 'success':
            data = response.get('data', [])
            target_suffix = f"{mmm}{yy}FUT"
            candidates = []
            for item in data:
                sym = item.get('symbol', '')
                if sym.endswith(target_suffix) and sym.startswith(SYMBOL_PREFIX):
                    if "BANK" in sym: continue
                    if sym[5:7].isdigit(): candidates.append(sym)
            if candidates: return candidates[0]
    except Exception:
        pass
    return None

def get_historical_candles(symbol):
    import requests
    url = f"{HOST}/api/v1/history"
    payload = {
        "apikey": API_KEY,
        "symbol": symbol,
        "exchange": EXCHANGE,
        "interval": "1m",
        "start_date": (datetime.now() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d"),
        "end_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") 
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict): return data.get("data", []) or data.get("data", {}).get("candles", [])
    except: pass
    return []

def calculate_indicators(candles):
    if not candles: return None
    df = pd.DataFrame(candles)
    map_cols = {'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'}
    df.rename(columns=map_cols, inplace=True)
    df['close'] = pd.to_numeric(df['close'])
    
    df['ema'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=RSI_PERIOD-1, adjust=False).mean()
    ma_down = down.ewm(com=RSI_PERIOD-1, adjust=False).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))

    k = df['close'].ewm(span=MACD_FAST, adjust=False).mean()
    d = df['close'].ewm(span=MACD_SLOW, adjust=False).mean()
    df['macd_line'] = k - d
    df['macd_signal'] = df['macd_line'].ewm(span=MACD_SIGNAL, adjust=False).mean()
    
    return df.iloc[-1]

def check_time_filter():
    now = datetime.now().time()
    morning_start = datetime.strptime(MORNING_START, "%H:%M").time()
    morning_end = datetime.strptime(MORNING_END, "%H:%M").time()
    afternoon_start = datetime.strptime(AFTERNOON_START, "%H:%M").time()
    afternoon_end = datetime.strptime(AFTERNOON_END, "%H:%M").time()
    return (morning_start <= now < morning_end) or (afternoon_start <= now < afternoon_end)

def check_exit_conditions(current_price):
    global position, stop_loss, take_profit, highest_price, lowest_price
    
    if position is None: return
        
    if position == "BULL_SPREAD":
        if current_price > highest_price:
            highest_price = current_price
            if (highest_price - entry_price) >= TSL_ACTIVATION_POINTS:
                new_sl = highest_price - TSL_TRAIL_POINTS
                if new_sl > stop_loss: stop_loss = new_sl

        if current_price <= stop_loss: close_position(current_price, "STOP LOSS/TSL")
        elif current_price >= take_profit: close_position(current_price, "TAKE PROFIT")
            
    elif position == "BEAR_SPREAD":
        if current_price < lowest_price:
            lowest_price = current_price
            if (entry_price - lowest_price) >= TSL_ACTIVATION_POINTS:
                new_sl = lowest_price + TSL_TRAIL_POINTS
                if new_sl < stop_loss: stop_loss = new_sl

        if current_price >= stop_loss: close_position(current_price, "STOP LOSS/TSL")
        elif current_price <= take_profit: close_position(current_price, "TAKE PROFIT")

def get_ltp(symbol):
    try:
        res = client.quotes(symbol=symbol, exchange=EXCHANGE)
        if hasattr(res, 'get') and res.get('status') == 'success':
             d = res.get('data')
             if d: return float(d.get('ltp', 0))
    except: pass
    return 0.0

def entry_loop():
    global current_symbol
    log("Starting Entry Loop...")
    while True:
        try:
            if not current_symbol:
                current_symbol = resolve_current_symbol()
                if not current_symbol:
                    time.sleep(60)
                    continue
                log(f"Active Symbol: {current_symbol}")

            now = datetime.now()
            time.sleep(60 - now.second + 2)
            
            if not check_time_filter(): continue

            candles = get_historical_candles(current_symbol)
            latest = calculate_indicators(candles)
            if latest is None: continue
                
            close = latest['close']
            ema = latest['ema']
            rsi = latest['rsi']
            macd_line = latest['macd_line']
            macd_signal = latest['macd_signal']
            
            if position is None:
                if close > ema and rsi < RSI_OVERSOLD and macd_line > macd_signal:
                    log(f"Signal [LONG] @ {close}")
                    place_order("BUY", close)
                elif close < ema and rsi > RSI_OVERBOUGHT and macd_line < macd_signal:
                    log(f"Signal [SHORT] @ {close}")
                    place_order("SELL", close)
                    
        except Exception as e:
            log(f"Entry Error: {e}")
            time.sleep(10)

def exit_loop():
    log("Starting Exit Loop...")
    while True:
        try:
            if position is not None and current_symbol:
                ltp = get_ltp(current_symbol)
                if ltp > 0: check_exit_conditions(ltp)
            time.sleep(5)
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    t_exit = threading.Thread(target=exit_loop, daemon=True)
    t_exit.start()
    entry_loop()

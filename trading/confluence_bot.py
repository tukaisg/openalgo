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
DRY_RUN = False  # LIVE TRADING ENABLED
IS_OPTION_BUYING = True # New Flag for Option Buying Mode
SYMBOL_PREFIX = "NIFTY"
EXCHANGE = "NFO"
TIMEFRAME_MINUTES = 1
HISTORY_DAYS = 5 # Fetch enough data for EMA 200
LOT_SIZE = 75 # Nifty Futures Lot Size (Adjust based on contract)

# Strategy Parameters
RSI_PERIOD = 14
RSI_OVERBOUGHT = 55 # Short entry
RSI_OVERSOLD = 45   # Long entry
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
current_symbol = None # This is the Signal Symbol (Futures)
traded_option_symbol = None # This is the Actual Instrument Traded (Opt)
position = None # None, 'LONG', 'SHORT' (Direction of trade)
entry_price = 0.0 # Entry Price of FUTURE
stop_loss = 0.0 # SL Level on FUTURE
take_profit = 0.0 # TP Level on FUTURE
highest_price = 0.0 # For TSL (Long)
lowest_price = 0.0  # For TSL (Short)

# ... (omitted helper functions) ...

def get_option_symbol(future_symbol, price, side):
    """
    Construct Option Symbol based on Future Symbol and ATM Strike.
    future_symbol: NIFTY30DEC25FUT
    price: Current Futures Price (e.g. 26179)
    side: 'BUY' (Call) or 'SELL' (Put) relative to Strategy Signal
    """
    try:
        # 1. Parse Expiry and Format from Future Symbol
        # Format: NIFTY + ddMMMyy + FUT
        # Option Format: NIFTY + ddMMMyy + Strike + CE/PE
        # Example: NIFTY30DEC2526200CE
        
        base = future_symbol.replace("FUT", "")
        
        # 2. Calc ATM Strike
        # Round to nearest 50
        strike = round(price / 50) * 50
        
        # 3. Determine Type
        # If Strategy Signal is BUY (Long), we Buy CE.
        # If Strategy Signal is SELL (Short), we Buy PE.
        # Note: 'side' passed here is the Strategy Signal.
        opt_type = "CE" if side == "BUY" else "PE"
        
        opt_symbol = f"{base}{strike}{opt_type}"
        return opt_symbol
    except Exception as e:
        log(f"Option Symbol Construct Error: {e}")
        return None

def place_order(side, price):
    global position, entry_price, stop_loss, take_profit, highest_price, lowest_price, traded_option_symbol
    
    order_symbol = current_symbol
    action = side
    
    if IS_OPTION_BUYING:
        # Determine Option Symbol
        opt_sym = get_option_symbol(current_symbol, price, side)
        if not opt_sym:
            log("ABORT: Could not determine Option Symbol.")
            return
        
        order_symbol = opt_sym
        traded_option_symbol = opt_sym
        action = "BUY" # Always BUY options for this strategy (Long Call or Long Put)
        
        log(f"[{'DRY RUN' if DRY_RUN else 'LIVE'}] Strategy Signal {side} @ {price}. Trading Option: {order_symbol} (Action: BUY)")
    else:
        log(f"[{'DRY RUN' if DRY_RUN else 'LIVE'}] Placed {side} Order for {current_symbol} at {price}")

    if DRY_RUN:
        # Simulate Fill
        if IS_OPTION_BUYING:
             position = "LONG" if side == "BUY" else "SHORT"
        else:
             position = side
             
        entry_price = price # We track FUTURE price for SL/TP
        
        if side == "BUY":
            stop_loss = entry_price - STOP_LOSS_POINTS
            take_profit = entry_price + TAKE_PROFIT_POINTS
            highest_price = entry_price
        else:
            stop_loss = entry_price + STOP_LOSS_POINTS
            take_profit = entry_price - TAKE_PROFIT_POINTS
            lowest_price = entry_price
            
        log(f"  -> Sim Position: {position} | Future Entry: {entry_price} | SL: {stop_loss}")
    else:
        # Live API Call
        try:
             response = client.placeorder(
                symbol=order_symbol,
                action=action,
                exchange=EXCHANGE,
                price_type="MARKET",
                product="MIS",
                quantity=LOT_SIZE
             )
             log(f"API Response: {response}")
             
             if response.get('status') == 'success':
                 if IS_OPTION_BUYING:
                     position = "LONG" if side == "BUY" else "SHORT"
                 else:
                     position = side
                 
                 entry_price = price
                 
                 if side == "BUY":
                    stop_loss = entry_price - STOP_LOSS_POINTS
                    take_profit = entry_price + TAKE_PROFIT_POINTS
                    highest_price = entry_price
                 else:
                    stop_loss = entry_price + STOP_LOSS_POINTS
                    take_profit = entry_price - TAKE_PROFIT_POINTS
                    lowest_price = entry_price
                    
                 log(f"  -> State Updated: {position} | SL: {stop_loss} | TP: {take_profit}")
             else:
                 log(f"Order Failed: {response.get('message')}")
                 
        except Exception as e:
             log(f"Order Exceptions: {e}")

def close_position(price, reason):
    global position, entry_price, stop_loss, take_profit, traded_option_symbol
    
    # price passed here is the Futures Price (trigger)
    log(f"[{'DRY RUN' if DRY_RUN else 'LIVE'}] Closing Position ({reason}). Trigger Price: {price}")
    
    exit_symbol = traded_option_symbol if IS_OPTION_BUYING and traded_option_symbol else current_symbol
    exit_action = "SELL" # For Option Buying, we Close by Selling. For Futures, opposite of pos.
    
    if not IS_OPTION_BUYING:
        exit_action = "SELL" if position == "BUY" else "BUY"
    
    if DRY_RUN:
        pnl_pts = 0
        if position == "LONG" or position == "BUY":
            pnl_pts = price - entry_price
        elif position == "SHORT" or position == "SELL":
            pnl_pts = entry_price - price
            
        log(f"  -> Sim PnL (Futures Pts): {pnl_pts:.2f}")
    else:
        try:
             response = client.placeorder(
                symbol=exit_symbol,
                action=exit_action,
                exchange=EXCHANGE,
                price_type="MARKET",
                product="MIS",
                quantity=LOT_SIZE
             )
             log(f"Exit API Response: {response}")
             if response.get('status') == 'success':
                 log("  -> Position Closed Successfully")
             else:
                 log(f"  -> Exit Failed: {response.get('message')}")
        except Exception as e:
            log(f"Exit Exception: {e}")
            
    position = None
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    traded_option_symbol = None

# --- Helper Functions ---

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def resolve_current_symbol():
    """Find the NIFTY Futures symbol for the current month."""
    now = datetime.now()
    mmm = now.strftime("%b").upper()
    yy = now.strftime("%y")
    
    query = f"{SYMBOL_PREFIX} {mmm} {yy}"
    log(f"Searching for symbol: {query}")
    
    try:
        response = client.search(query=query, exchange=EXCHANGE)
        if isinstance(response, dict) and response.get('status') == 'success':
            data = response.get('data', [])
            target_suffix = f"{mmm}{yy}FUT"
            
            candidates = []
            for item in data:
                sym = item.get('symbol', '')
                if sym.endswith(target_suffix) and sym.startswith(SYMBOL_PREFIX):
                    # Strict check to avoid BANKNIFTY if searching NIFTY
                    # NIFTY... starts with NIFTY. BANKNIFTY starts with BANK.
                    # But verify purely to be safe.
                    if "BANK" in sym:
                        continue

                    # NIFTY... starts with NIFTY and 6th char is digit (day)
                    if sym[5:7].isdigit(): 
                        candidates.append(sym)
            
            if candidates:
                # Sort to ensure consistent selection (e.g. if multiple expiries or weekly/monthly overlap)
                # Typically monthly has 'FUT' suffix.
                # Just pick first valid one.
                return candidates[0]
                
    except Exception as e:
        log(f"Symbol Search Error: {e}")
        
    return None

def fetch_data(symbol):
    """Fetch historical data for indicators."""
    try:
        # Calculate start time for history (e.g. 5 days ago)
        # OpenAlgo needs date string YYYY-MM-DD
        end_date = datetime.now()
        start_date = end_date - timedelta(days=HISTORY_DAYS)
        
        # We need to map 1 minute to OpenAlgo interval
        # Usually '1m'
        
        response = client.data(
            symbol=symbol,
            exchange=EXCHANGE,
            interval="1m",
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d") # API might expect 'end' or 'end_date' depending on version. 
            # The SDK wrapper might map 'start_date' and 'end_date' or just take kwargs.
            # Based on previous usage in OAStore, it uses 'start' and 'end_date'.
            # But raw client.keys might differ. Let's try standard 'start'/'end'.
        )
        # Re-checking SDK usage from memory or files... 
        # OAStore used `client.historical(symbol, interval, start, end)`.
        # Wait, the SDK `instruments` and `quotes` were seen. 
        # Let's assume there is a historical method. 
        # If not, we might need to use `client.get_history` or similar.
        # Actually, let's look at `openalgo/api.py` if needed.
        # For now, let's assume `client.historical` exists or similar.
        # FIX: The `OAStore` uses `self.client._make_request("historical", payload)`.
        # So `client.historical` should work if it exposes it, or we use `client._make_request`.
        # SDK usage in `rsi_scalping.py` used `OAStore`. 
        # Let's use `OAStore` logic or just `requests` if SDK is thin.
        # Actually, let's try `client.historical`.
        pass 
    except:
        pass

# Redefine fetch to use requests/direct api if SDK is ambiguous, ONE MOMENT.
# I will use OAStore logic to fetch data since it is proven to work.
# Actually, I can just copy the `fetch_historical` logic from OAStore or import OAStore?
# Importing OAStore adds Backtrader dependency which is fine but maybe heavy for a simple bot?
# Let's just implement a simple fetch using the `client` object if possible.
# I'll stick to a robust implementation below.

def get_historical_candles(symbol):
    import requests
    url = f"{HOST}/api/v1/history"
    
    # OpenAlgo API expects POST with JSON body for history often, or specific params.
    # Based on openalgo_bt/utils/history.py:
    # url = f"{api_host}/api/v1/history"
    # payload = { "apikey": ..., "symbol": ..., "exchange": ..., "interval": ..., "start_date": ..., "end_date": ... }
    
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
        
        # Parse response logic from history.py
        candles = []
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                candles = data["data"]
            elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("candles"), list):
                candles = data["data"]["candles"]
        elif isinstance(data, list):
            candles = data
            
        return candles

    except Exception as e:
        log(f"Fetch Error: {e}")
    return []

def calculate_indicators(candles):
    if not candles: return None
    df = pd.DataFrame(candles)
    # Rename: o, h, l, c, v, t
    map_cols = {'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'}
    df.rename(columns=map_cols, inplace=True)
    df['close'] = pd.to_numeric(df['close'])
    
    # EMA 200
    df['ema'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    
    # RSI 14 (Fixing usage)
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    # Remove 'probs=None'
    ma_up = up.ewm(com=RSI_PERIOD-1, adjust=False).mean()
    ma_down = down.ewm(com=RSI_PERIOD-1, adjust=False).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
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
    
    is_morning = morning_start <= now < morning_end
    is_afternoon = afternoon_start <= now < afternoon_end
    
    return is_morning or is_afternoon

def check_exit_conditions(current_price):
    global position, stop_loss, take_profit, highest_price, lowest_price
    
    if position is None: return
        
    if position == "BUY" or position == "LONG":
        if current_price > highest_price:
            highest_price = current_price
            profit_points = highest_price - entry_price
            if profit_points >= TSL_ACTIVATION_POINTS:
                new_sl = highest_price - TSL_TRAIL_POINTS
                if new_sl > stop_loss:
                    stop_loss = new_sl
                    log(f"  -> Trailing SL Updated to {stop_loss:.2f}")

        if current_price <= stop_loss:
            close_position(current_price, "STOP LOSS / TRAILING SL")
        elif current_price >= take_profit:
            close_position(current_price, "TAKE PROFIT")
            
    elif position == "SELL" or position == "SHORT":
        if current_price < lowest_price:
            lowest_price = current_price
            profit_points = entry_price - lowest_price
            if profit_points >= TSL_ACTIVATION_POINTS:
                new_sl = lowest_price + TSL_TRAIL_POINTS
                if new_sl < stop_loss:
                    stop_loss = new_sl
                    log(f"  -> Trailing SL Updated to {stop_loss:.2f}")

        if current_price >= stop_loss:
            close_position(current_price, "STOP LOSS / TRAILING SL")
        elif current_price <= take_profit:
            close_position(current_price, "TAKE PROFIT")

def get_ltp(symbol):
    try:
        # Use DataAPI quotes or similar
        # Fallback to requests if lazy
        import requests
        url = f"{HOST}/api/v1/quotes" # or ticker
        # Based on check_price.py logic
        # client.quotes(symbol=..., exchange=...)
        res = client.quotes(symbol=symbol, exchange=EXCHANGE)
        if hasattr(res, 'get') and res.get('status') == 'success':
             # Format might be dict or list
             d = res.get('data')
             if d:
                 # d might be {"symbol": ..., "v": ..., "lp": ...}
                 # or a list. 
                 # check_price.py used logic to parse it. 
                 # Let's assume standard format: {'ltp': float}
                 return float(d.get('ltp', 0))
    except:
        pass
    return 0.0

# --- Main Threads ---

def entry_loop():
    global current_symbol
    log("Starting Entry Loop...")
    
    while True:
        try:
            # 1. Resolve Symbol (Once or periodially? Let's do every loop for safety or cache inside)
            if not current_symbol:
                current_symbol = resolve_current_symbol()
                if not current_symbol:
                    log("Could not resolve symbol. Retrying in 1 min...")
                    time.sleep(60)
                    continue
                log(f"Active Symbol: {current_symbol}")

            # 2. Wait for next minute candle close (roughly)
            # Sleep until next minute start + few seconds
            now = datetime.now()
            sleep_sec = 60 - now.second + 2 # +2s buffer
            time.sleep(sleep_sec)
            
            # 3. Check Time Filter
            if not check_time_filter():
                # Allow exits, but no new entries
                # We typically don't clear symbol here
                continue

            # 4. Fetch Data & Calc Indicators
            candles = get_historical_candles(current_symbol)
            if not candles:
                log("No candles fetched.")
                continue
                
            latest = calculate_indicators(candles)
            if latest is None:
                continue
                
            close = latest['close']
            ema = latest['ema']
            rsi = latest['rsi']
            macd_line = latest['macd_line']
            macd_signal = latest['macd_signal']
            
            # log(f"Indicators: Price={close} EMA={ema:.2f} RSI={rsi:.2f} MACD={macd_line:.2f}/{macd_signal:.2f}")
            
            # 5. Entry Logic
            if position is None:
                # LONG
                if close > ema and rsi < RSI_OVERSOLD and macd_line > macd_signal:
                    log(f"Entry Signal [LONG]: Price={close} > EMA={ema:.2f}, RSI={rsi:.2f} < {RSI_OVERSOLD}, MACD Bullish")
                    place_order("BUY", close)
                
                # SHORT
                elif close < ema and rsi > RSI_OVERBOUGHT and macd_line < macd_signal:
                    log(f"Entry Signal [SHORT]: Price={close} < EMA={ema:.2f}, RSI={rsi:.2f} > {RSI_OVERBOUGHT}, MACD Bearish")
                    place_order("SELL", close)
                    
        except Exception as e:
            log(f"Entry Loop Error: {e}")
            time.sleep(10)

def exit_loop():
    log("Starting Exit Loop...")
    while True:
        try:
            if position is not None and current_symbol:
                ltp = get_ltp(current_symbol)
                if ltp > 0:
                    check_exit_conditions(ltp)
            
            time.sleep(5) # Poll every 5s
        except Exception as e:
            log(f"Exit Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Start Exit Loop in background
    t_exit = threading.Thread(target=exit_loop, daemon=True)
    t_exit.start()
    
    # Run Entry Loop in main thread
    entry_loop()

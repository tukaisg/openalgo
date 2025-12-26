import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from openalgo import api

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
API_KEY = os.getenv("OPENALGO_API_KEY")
HOST = "http://127.0.0.1:5000"
EXCHANGE = "NFO"
CLIENT_ID = "YourID" # Optional check

if not API_KEY:
    print("Error: OPENALGO_API_KEY not found.")
    sys.exit(1)

client = api(api_key=API_KEY, host=HOST)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def search_future():
    # Helper to find current month future
    now = datetime.now()
    mmm = now.strftime("%b").upper()
    yy = now.strftime("%y")
    # Using the one we know works
    symbol = f"NIFTY30DEC{yy}FUT" 
    # Or search dynamically if preferred, but hardcoding for stability in demo
    return symbol

def get_quotes_batch(symbols):
    # Fetch quotes for multiple symbols
    # OpenAlgo might not support batch in one go easily via simple GET, 
    # but let's try looping or comma separated if supported.
    # Standard: Loop.
    data = {}
    for sym in symbols:
        try:
             url = f"{HOST}/api/v1/quotes?exchange={EXCHANGE}&symbol={sym}&apikey={API_KEY}"
             # Note: Using GET format commonly used. If POST required, adjust.
             # Earlier we used client.quotes().
             # Let's use the SDK 'client' approach via requests to mimic it strictly?
             # Or just use the known working `client.quotes` logic.
             # Since this file doesn't import `api` class directly to avoid deps, I'll use requests.
             # Wait, `client.quotes` uses GET /quotes usually.
             
             res = requests.get(url, timeout=2)
             if res.status_code == 200:
                 d = res.json()
                 if d.get('status') == 'success':
                     data[sym] = d.get('data', {})
        except: pass
    return data

def analyze_oi():
    # 1. Resolve Symbols
    fut_sym = search_future()
    
    # Initial Fetch to get ATM
    try:
        # Use SDK client
        r = client.quotes(exchange=EXCHANGE, symbol=fut_sym)
        if r.get('status') == 'success':
             d = r.get('data', {})
             ltp = float(d.get('ltp', 0))
        else:
             log(f"Fetch Fail: {r}")
             ltp = 0
             
    except Exception as e:
        log(f"Exception: {e}")
        ltp = 0
        
    if ltp == 0:
        log(f"Failed to fetch Future Price for {fut_sym}")
        return

    # ROI: 50
    strike = round(ltp / 50) * 50
    base = fut_sym.replace("FUT", "")
    ce_sym = f"{base}{strike}CE"
    pe_sym = f"{base}{strike}PE"
    
    log(f"--- Monitoring {fut_sym} & ATM {strike} ---")
    log("TIME     | FUT Price | FUT OI      | SIGNAL        | PCR (ATM)")
    log("-" * 65)
    
    prev_fut_price = ltp
    prev_fut_oi = float(d.get('oi', 0))
    
    while True:
        try:
            # Fetch Data via SDK
            q_fut = client.quotes(exchange=EXCHANGE, symbol=fut_sym).get('data', {})
            q_ce = client.quotes(exchange=EXCHANGE, symbol=ce_sym).get('data', {})
            q_pe = client.quotes(exchange=EXCHANGE, symbol=pe_sym).get('data', {})
            
            # Extract
            f_price = float(q_fut.get('ltp', 0))
            f_oi = float(q_fut.get('oi', 0))
            
            ce_oi = float(q_ce.get('oi', 0))
            pe_oi = float(q_pe.get('oi', 0))
            
            # Analysis
            signal = "Neutral"
            if f_price > prev_fut_price and f_oi > prev_fut_oi:
                signal = "Long Buildup (Bull)"
            elif f_price < prev_fut_price and f_oi > prev_fut_oi:
                signal = "Short Buildup (Bear)"
            elif f_price < prev_fut_price and f_oi < prev_fut_oi:
                signal = "Long Unwind (Weak)"
            elif f_price > prev_fut_price and f_oi < prev_fut_oi:
                signal = "Short Covering (Bull)"
            
            pcr = pe_oi / ce_oi if ce_oi > 0 else 0
            
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"{timestamp} | {f_price:9.2f} | {f_oi:11.0f} | {signal:13} | {pcr:.2f}")
            
            # Update history
            prev_fut_price = f_price
            prev_fut_oi = f_oi
            
            # Reset Strike if price moves too much?
            # For strict monitoring, we usually stick to one strike or update it.
            # Let's stick to initial ATM for this session.
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    analyze_oi()

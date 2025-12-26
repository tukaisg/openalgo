import os
import sys

# Set API Key explicitly before imports so history.py picks it up
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

try:
    from openalgo_bt.stores.oa import OAStore
    import backtrader as bt
    from datetime import datetime, timedelta

    print("Initializing OAStore...")
    store = OAStore()
    
    # Test fetch_historical
    symbol = "NSE:SBIN" # Use a common symbol
    # Use dates that likely have data. OpenAlgo history depends on what's available or if it fetches from broker.
    # Since we set up Fyers, it should fetch from Fyers if allowed.
    # But Fyers history API might require 'history' access.
    
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"Fetching history for {symbol} from {start_date} to {end_date}...")
    
    try:
        candles = store.fetch_historical(
            symbol=symbol,
            start=start_date,
            end_date=end_date,
            interval="D"
        )
        print(f"Fetched {len(candles)} candles.")
        if candles:
            print("First candle:", candles[0])
            print("Last candle:", candles[-1])
            
    except Exception as e:
        print(f"fetch_historical failed: {e}")
        # It might fail if no data or broker error.
        
except Exception as e:
    print(f"Error testing Backtrader lib: {e}")
    import traceback
    traceback.print_exc()

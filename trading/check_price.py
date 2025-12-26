import os
from dotenv import load_dotenv
from openalgo import api

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

api_key = os.getenv("OPENALGO_API_KEY")
host = "http://127.0.0.1:5000"

try:
    client = api(api_key=api_key, host=host)
    # Nifty 50 is commonly NSE_INDEX:NIFTY or similar. Trying standard NIFTY first.
    # The client.get_quote might expect "NSE_INDEX:NIFTY" or just "NIFTY" depending on usage.
    # Based on SDK docs (or common usage), exchange usually needs to be specified if not in symbol string 
    # OR symbol string should have it. 
    # Let's try specifying specific params if possible or just the symbol string if the SDK handles it.
    # Looking at test_sdk.py... client.optionsorder used params. 
    # Let's try client.get_quote usage. `client.quote` or `client.get_quote`?
    # __init__.py inherited DataAPI. DataAPI likely has `quote`.
    
    symbol = "NSE_INDEX:NIFTY 50" 
    # Or just "NIFTY 50" if exchange is separate.
    # Let's try to list or just guess "NSE_INDEX:NIFTY 50" creates a clear intent. 
    # Wait, indices are usually just "NIFTY". "NIFTY 50" might be the name.
    # Let's try "NSE_INDEX:NIFTY 50".
    
    # Found correct symbol: 'NIFTY' on 'NSE_INDEX'
    # API method is quotes(symbol=..., exchange=...)
    # User requested: NIFTY30DEC25FUT
    # Futures are on NFO exchange
    try:
        symbol = "NIFTY30DEC25FUT"
        exchange = "NFO"
        
        print(f"Fetching quote for {symbol} on {exchange}...")
        response = client.quotes(symbol=symbol, exchange=exchange)
        if response.get('status') == 'success':
            data = response.get('data', {})
            print(f"DEBUG Raw Data: {data}") # Kept for verification
            
            # Data is a flat dict as seen in debug output
            ltp = data.get('ltp')
            prev_close = data.get('prev_close')
            
            change = 0
            change_percent = 0
            if ltp and prev_close:
                change = ltp - prev_close
                if prev_close != 0:
                    change_percent = (change / prev_close) * 100
                
            print(f"✅ Symbol: {symbol}")
            print(f"💰 LTP:    {ltp}")
            print(f"📈 Change: {change:.2f} ({change_percent:.2f}%)")
        else:
            print(f"❌ Error: {response.get('message')}")
    except AttributeError:
        print("Error: 'quotes' method not found via api object. Checking dir list...")
        print(dir(client))

except Exception as e:
    print(f"❌ Error: {str(e)}")

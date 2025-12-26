import os
from dotenv import load_dotenv
from openalgo import api

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
api_key = os.getenv("OPENALGO_API_KEY")
host = "http://127.0.0.1:5000"
client = api(api_key=api_key, host=host)

def verify_construction():
    # 1. Find Future
    print("Searching for NIFTY DEC 25 Future...")
    # Based on earlier logs: NIFTY30DEC25FUT
    fut_res = client.search(query="NIFTY DEC 25", exchange="NFO")
    
    future_symbol = "NIFTY30DEC25FUT" # Default/Fallback
    
    if fut_res.get('status') == 'success':
        data = fut_res.get('data', [])
        # Look for the specific one we saw
        cands = [x['symbol'] for x in data if "NIFTY30DEC25FUT" in x['symbol']]
        if cands:
            future_symbol = cands[0]
            print(f"Found Future: {future_symbol}")
        else:
            print("Could not find exact future in search, using default.")
            
    # 2. Construct Option Symbol (ATM approx 26200)
    base = future_symbol.replace("FUT", "")
    strike = 26200
    opt_type = "CE"
    
    constructed_symbol = f"{base}{strike}{opt_type}"
    print(f"Constructed Option Symbol: {constructed_symbol}")
    
    # 3. Test Existence via Search (Safer)
    print(f"Verifying via Search for Strike {strike}...")
    
    # We want NIFTY Options near this strike.
    # Query: "NIFTY {Strike} {Type}" e.g. "NIFTY 26200 CE"
    query = f"NIFTY {strike} {opt_type}"
    print(f"Searching: '{query}'")
    
    s_res = client.search(query=query, exchange="NFO")
    if s_res.get('status') == 'success':
        data = s_res.get('data', [])
        # print first 5
        print(f"Found {len(data)} candidates.")
        for d in data[:5]:
            print(f"  {d['symbol']}")
            
        # We need to pick the one closely matching the Future's expiry.
        # Future: NIFTY30DEC25FUT (Dec 2025)
        # Option candidates might be: NIFTY04DEC25..., NIFTY30DEC25...
        # We need to find the one with the same Month/Year.
        # But wait, earlier debug showed NIFTY23DEC25...
        # So correct expiry might be 23DEC25.
        
        # Let's see what the search returns.
    else:
        print("Search failed.")

if __name__ == "__main__":
    verify_construction()

import os
import sys
import calendar
from datetime import datetime, timedelta, date, time
import backtrader as bt
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

try:
    from openalgo_bt.stores.oa import OAStore
except ImportError:
    pass

# --- Helper Functions (Stitching) - Reused ---
SYMBOL_CACHE = {}
def resolve_nifty_symbol(store, year, month):
    mmm = date(year, month, 1).strftime("%b").upper()
    yy = date(year, month, 1).strftime("%y")
    cache_key = f"{mmm}{yy}"
    if cache_key in SYMBOL_CACHE: return SYMBOL_CACHE[cache_key]
    query = f"NIFTY {mmm} {yy}"
    try:
        response = store.client.search(query=query, exchange="NFO")
        if isinstance(response, dict) and response.get('status') == 'success':
            candidates = [i.get('symbol', '') for i in response.get('data', [])]
            valid = [c for c in candidates if c.endswith(f"{mmm}{yy}FUT") and c.startswith("NIFTY") and c[5:7].isdigit()]
            if valid:
                SYMBOL_CACHE[cache_key] = valid[0]
                return valid[0]
    except Exception: pass
    return None

def fetch_and_stitch_data(store, days=200):
    end_date_limit = datetime.now()
    start_date_limit = end_date_limit - timedelta(days=days)
    all_dfs = []
    print(f"--- Stitching Data for Synthetic Straddle (last {days} days) ---")
    
    iter_date = start_date_limit.replace(day=1)
    months = sorted(list(set([(d.year, d.month) for d in [start_date_limit + timedelta(days=32*i) for i in range(8)] if d <= end_date_limit])))
    
    last_expiry = None
    
    for year, month in months:
        symbol_base = resolve_nifty_symbol(store, year, month)
        if not symbol_base: continue
        symbol_full = f"NFO:{symbol_base}"
        try:
            exp = datetime.strptime(symbol_base[5:12], "%d%b%y").date()
        except: continue

        fetch_end = min(datetime.combine(exp, datetime.max.time()), end_date_limit)
        fetch_start = max(datetime.combine(last_expiry + timedelta(days=1), datetime.min.time()) if last_expiry else start_date_limit, start_date_limit)
        
        if fetch_start >= fetch_end:
            last_expiry = exp
            continue
            
        print(f"Fetching {symbol_full}...")
        try:
            candles = store.fetch_historical(
                symbol=symbol_full, 
                start=fetch_start.strftime("%Y-%m-%d"), 
                end_date=(fetch_end + timedelta(days=1)).strftime("%Y-%m-%d"), 
                interval=store.bt_to_interval(bt.TimeFrame.Minutes, 1)
            )
            if candles:
                df = pd.DataFrame(candles)
                df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume','t':'timestamp'}, inplace=True)
                if 'timestamp' in df.columns:
                     first = df['timestamp'].iloc[0]
                     if isinstance(first, (int, float)): df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
                     else: df['datetime'] = pd.to_datetime(df['timestamp'])
                if 'datetime' in df.columns:
                    df.set_index('datetime', inplace=True)
                    df = df[(df.index >= fetch_start) & (df.index <= fetch_end)]
                    if not df.empty: all_dfs.append(df)
        except: pass
        last_expiry = exp

    if not all_dfs: return None
    final_df = pd.concat(all_dfs)
    final_df.sort_index(inplace=True)
    return final_df[~final_df.index.duplicated(keep='first')]

# --- Synthetic Strategy Logic ---
# Since Backtrader is complex for generic PnL simulation without real option objects,
# We will use Pandas iteration for the Synthetic Backtest. It's faster and cleaner for this "Proxy" logic.

def run_synthetic_backtest():
    store = OAStore()
    df = fetch_and_stitch_data(store, days=200)
    
    if df is None or df.empty:
        print("No Data found.")
        return

    # Filter Trading Hours 09:15 to 15:30
    df = df.between_time("09:15", "15:30")
    
    # Resample to Daily to iterate days? No, we need Intraday Entry/Exit.
    # Group by Date
    dates = df.index.date
    unique_dates = sorted(list(set(dates)))
    
    print(f"Analyzing {len(unique_dates)} Trading Days...")
    
    stats = []
    
    PREMIUM_PCT = 0.008 # 0.8% of Spot (ATM Straddle Premium Estimate)
    STOP_LOSS_PCT = 0.004 # 0.4% Move (approx 50% of Premium collected) - Stop Loss on Spot Move
    # Note: Real SL is on Premium. If Spot moves 0.4%, Premium likely spikes.
    
    # Let's say we collected 200 pts. If Spot moves 100 pts, Delta loss is ~50 pts.
    # Synthetic Logic:
    # Credit = Open * 0.008
    # We exit at 15:00 OR if Price moves > predefined threshold (SL).
    
    for d in unique_dates:
        day_df = df[df.index.date == d]
        
        # Entry at 09:20
        entry_time = time(9, 20)
        exit_time = time(15, 0)
        
        try:
            entry_row = day_df.loc[day_df.index.time >= entry_time].iloc[0]
            entry_price = entry_row['open']
            
            # Premium Collected
            premium_collected = entry_price * PREMIUM_PCT
            
            # Stop Loss Level (Spot based simulation)
            upper_sl = entry_price * (1 + STOP_LOSS_PCT)
            lower_sl = entry_price * (1 - STOP_LOSS_PCT)
            
            # Check for SL hit during day
            # We look at data after entry
            session_df = day_df.loc[day_df.index >= entry_row.name]
            
            # Did we hit SL?
            sl_hit_idx = session_df[(session_df['high'] >= upper_sl) | (session_df['low'] <= lower_sl)].index
            
            exit_price = 0
            exit_reason = ""
            
            if not sl_hit_idx.empty:
                # SL Hit
                sl_time = sl_hit_idx[0]
                # Assuming we exit at the breach Price (approx)
                # If gap up/down, we take slippage? Synthetic: Just take SL level.
                # Or actul close of that candle.
                hit_candle = session_df.loc[sl_time]
                if hit_candle['high'] >= upper_sl: exit_price = upper_sl
                else: exit_price = lower_sl
                
                exit_reason = "SL"
            else:
                # Exit at 15:00
                exit_cand = session_df.loc[session_df.index.time >= exit_time]
                if not exit_cand.empty:
                    exit_price = exit_cand.iloc[0]['close']
                    exit_reason = "TIME"
                else:
                    exit_price = session_df.iloc[-1]['close'] # End of day
                    exit_reason = "EOD"
            
            # PnL Calculation
            # Short Straddle PnL = Premium Collected - |Exit - Entry|
            movement = abs(exit_price - entry_price)
            pnl = premium_collected - movement
            
            stats.append({
                'Date': d,
                'Entry': entry_price,
                'Exit': exit_price,
                'Premium': premium_collected,
                'Movement': movement,
                'PnL': pnl,
                'Reason': exit_reason
            })
            
        except IndexError:
            continue

    # Stats
    res_df = pd.DataFrame(stats)
    total_trades = len(res_df)
    wins = len(res_df[res_df['PnL'] > 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    total_pnl = res_df['PnL'].sum()
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    print("\n--- Synthetic Short Straddle Results (Nifty Futures Proxy) ---")
    print(f"Days Tested: {total_trades}")
    print(f"Win Rate: {win_rate:.2f}%") # How often market stays within range
    print(f"Total Points PnL: {total_pnl:.2f}")
    print(f"Avg PnL per Day: {avg_pnl:.2f}")
    print(f"Estimated Profit (1 Lot = 75): ₹{total_pnl * 75:.2f}")

if __name__ == '__main__':
    run_synthetic_backtest()

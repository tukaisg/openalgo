import os
import sys
import calendar
from datetime import datetime, timedelta, date, time
import backtrader as bt
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

try:
    from openalgo_bt.stores.oa import OAStore
except ImportError:
    pass

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
    # Reuse stitching logic from before to get clean data
    end_date_limit = datetime.now()
    start_date_limit = end_date_limit - timedelta(days=days)
    all_dfs = []
    print(f"--- Stitching Data for VWAP Strategy (last {days} days) ---")
    
    iter_date = start_date_limit.replace(day=1)
    months = []
    while iter_date <= end_date_limit:
        months.append((iter_date.year, iter_date.month))
        iter_date += timedelta(days=32)
        iter_date = iter_date.replace(day=1)
    
    months = sorted(list(set(months)))
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
                     # Handle timestamp logic similar to before
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

# Pre-calculate VWAP in Pandas to avoid Backtrader complexity with daily resets
def add_vwap(df):
    # Group by Date
    df['date'] = df.index.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_pv'] = df.groupby('date').apply(lambda x: (x['close'] * x['volume']).cumsum()).reset_index(level=0, drop=True)
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    df.drop(columns=['date', 'cum_vol', 'cum_pv'], inplace=True)
    return df

class VWAPStrategy(bt.Strategy):
    params = (
        ('ema_period', 200),
        ('rsi_period', 14),
        ('rsi_max', 60), # Don't buy if RSI > 60
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.params.ema_period)
        self.rsi = bt.indicators.RSI_Safe(self.data.close, period=self.params.rsi_period)
        self.vwap = self.data.vwap # Custom line from PandasData

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.log(f'ORDER EXECUTED ({order.ordtypename()}), Price: {order.executed.price:.2f}')

    def next(self):
        if self.position:
            # Exit Conditions: 
            # If SHORT (Fade): Exit if Price closes BELOW VWAP? No, we sold at VWAP hoping for rejection down.
            # So standard exit: Price < EMA 200 (Trend Change) or profit target.
            # Let's keep it simple: Close if Price < VWAP is NOT correct for Fade. 
            # If we Sell at VWAP, we expect price to drop.
            # Let's use a fixed target or Time Exit.
            # Or revert to original exit logic inverted?
            # Original: Exit (Close) if Price < VWAP
            # New (Short): Exit (Cover) if Price > VWAP? No, that's stop loss.
            
            # Let's use a simpler Time Exit or just Close if Price < EMA (Trend Reversal).
            # But the user asked to "reverse logic".
            # Original Buy: Close > EMA & Cross Above VWAP.
            # Reversed (Sell): Close > EMA & Cross Above VWAP -> SELL. (Betting on False Breakout).
            
            pass 

        # Entry Conditions (Reversed)
        # Original: If Price > EMA & Cross Above VWAP -> BUY
        # New: If Price > EMA & Cross Above VWAP -> SELL (Fade the breakout)
        
        # Time Filter
        dt = self.datas[0].datetime.datetime(0).time()
        morning = (dt >= time(9, 15)) and (dt < time(11, 0))
        afternoon = (dt >= time(13, 0)) and (dt < time(15, 0))
        
        if (morning or afternoon):
            if self.data.close[0] > self.ema[0]: # Uptrend context
                # Crossover: Prev Close < Prev VWAP AND Curr Close > Curr VWAP
                if self.data.close[-1] < self.vwap[-1] and self.data.close[0] > self.vwap[0]:
                    if self.rsi[0] < self.params.rsi_max: # Low RSI on breakout? 
                        # If fading, maybe we want High RSI? But let's stick to strict logic reversal first.
                        # Actually user said "reverse the logic of buy and sell".
                        # So Signal is same -> Action is opposite.
                        
                        if not self.position:
                             self.log(f"SELL ENTRY (Fade VWAP Breakout), Close: {self.data.close[0]:.2f}, VWAP: {self.vwap[0]:.2f}")
                             self.sell()
                             
        # Exit Logic for Short
        if self.position.size < 0:
             # Exit if Price Drops significantly below VWAP?
             # Or if Price closes back below VWAP (Fakeout confirmed, take profit?)
             # Let's say if Price < VWAP - 0.2%?
             # For simplicity in this test: Exit if Price < VWAP (The original exit condition was Price < VWAP).
             # If we are Short, Price < VWAP is GOOD. So we should hold? 
             # Original Exit: Price < VWAP (Stop Loss for Long).
             # Reversed Exit: Price < VWAP (Take Profit for Short).
             if self.data.close[0] < self.vwap[0]:
                 self.log(f"EXIT SHORT (Profit?), Close: {self.data.close[0]:.2f}, VWAP: {self.vwap[0]:.2f}")
                 self.close()

def run_strategy():
    store = OAStore()
    df = fetch_and_stitch_data(store, days=200)
    if df is None: return

    # Calculate VWAP
    df = add_vwap(df)
    
    # Custom Feed with VWAP column
    class VWAPData(bt.feeds.PandasData):
        lines = ('vwap',)
        params = (
            ('datetime', None),
            ('open', 'open'), ('high', 'high'), ('low', 'low'), ('close', 'close'), ('volume', 'volume'),
            ('vwap', 'vwap'),
        )
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(VWAPStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.adddata(VWAPData(dataname=df))
    cerebro.broker.setcash(100000.0)
    
    print('Starting Value: %.2f' % cerebro.broker.getvalue())
    results = cerebro.run()
    
    strat = results[0]
    ta = strat.analyzers.trades.get_analysis()
    total = ta.total.closed
    wins = ta.won.total
    rate = (wins/total*100) if total > 0 else 0
    print(f"\n--- VWAP Strategy Stats ---")
    print(f"Total Trades: {total}")
    print(f"Win Rate: {rate:.2f}%")
    print(f"Net PnL: {ta.pnl.net.total:.2f}")

if __name__ == '__main__':
    run_strategy()

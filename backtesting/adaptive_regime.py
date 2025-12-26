import os
import sys
import calendar
from datetime import datetime, timedelta, date, time
import backtrader as bt
import pandas as pd
import math
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

try:
    from openalgo_bt.stores.oa import OAStore
except ImportError:
    pass

# --- Helper Functions (Stitching) ---
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
    print(f"--- Stitching Data for Adaptive Strategy (last {days} days) ---")
    
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

# --- Custom Indicators ---

class ChoppinessIndex(bt.Indicator):
    lines = ('chop',)
    params = (('period', 14),)

    def __init__(self):
        # 100 * Log10( Sum(ATR(1), n) / (MaxHi(n) - MinLo(n)) ) / Log10( n )
        # ATR(1) is actually True Range.
        tr = bt.indicators.TrueRange(self.data)
        self.sum_tr = bt.indicators.SumN(tr, period=self.params.period)
        
        self.max_hi = bt.indicators.Highest(self.data.high, period=self.params.period)
        self.min_lo = bt.indicators.Lowest(self.data.low, period=self.params.period)
        
    def next(self):
        # Avoid division by zero
        range_diff = self.max_hi[0] - self.min_lo[0]
        if range_diff == 0:
            self.lines.chop[0] = 50 # Default middle
            return
            
        x = self.sum_tr[0] / range_diff
        if x <= 0:
            self.lines.chop[0] = 0
            return
            
        # Log10(x) / Log10(period) * 100
        self.lines.chop[0] = 100 * (math.log10(x) / math.log10(self.params.period))

# --- Strategy ---

class AdaptiveRegimeStrategy(bt.Strategy):
    params = (
        ('chop_period', 14),
        ('conf_ema', 200),
        ('conf_rsi_overbought', 55), # Short entry filter
        ('conf_rsi_oversold', 45),   # Long entry filter
        ('bb_period', 20),
        ('bb_dev', 2.0),
    )

    def __init__(self):
        # Regime Indicator
        self.chop = ChoppinessIndex(self.data, period=self.params.chop_period)
        
        # Trend Indicators (Confluence)
        self.ema = bt.indicators.EMA(self.data.close, period=self.params.conf_ema)
        self.rsi = bt.indicators.RSI_Safe(self.data.close, period=14)
        self.macd = bt.indicators.MACD(self.data.close)
        
        # Range Indicators (BB)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.params.bb_period, devfactor=self.params.bb_dev)
        
        self.regime = "UNKNOWN"

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'{dt.isoformat()} [{self.regime}] {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            type_str = "BUY" if order.isbuy() else "SELL"
            self.log(f'{type_str} EXECUTED, Price: {order.executed.price:.2f}')

    def next(self):
        if self.position:
            # Exit Logic
            # Common exit logic or regime specific?
            # Let's use simple exits to test entry quality primarily.
            # Or use BB Mid for everything?
            # If Trend: Exit on Macd Cross back?
            # If Range: Exit on BB Mid.
            
            # Simple universal exit for now: 
            # If Long and Price < EMA (Trend Broken) OR Hit BB Upper (Target)?
            # Let's try regime specific exits.
            
            if self.regime == "TREND":
                # Exit if MACD Cross signals reversal
                if self.position.size > 0 and self.macd.macd[0] < self.macd.signal[0]:
                     self.log("Exit Long (Trend Reversal MACD)")
                     self.close()
                elif self.position.size < 0 and self.macd.macd[0] > self.macd.signal[0]:
                     self.log("Exit Short (Trend Reversal MACD)")
                     self.close()
            elif self.regime == "RANGE":
                # Exit at Median
                if self.position.size > 0 and self.data.close[0] >= self.bb.lines.mid[0]:
                     self.log("Exit Long (BB Mean)")
                     self.close()
                elif self.position.size < 0 and self.data.close[0] <= self.bb.lines.mid[0]:
                     self.log("Exit Short (BB Mean)")
                     self.close()
                     
            return

        # Determine Regime
        # CHOP > 61.8 (High) -> Range
        # CHOP < 38.2 (Low) -> Trend
        # Using 50 as hard cutoff per plan, or stricter? 
        # Plan said: > 50 Range, < 50 Trend. Let's try that first.
        # Ideally using 38/61 helps filter "Noise" (Transitioning).
        # Let's use strict filters: < 45 Trend, > 55 Range. (Buffer zone no trade)
        
        chop_val = self.chop[0]
        
        # Time Filter
        dt = self.datas[0].datetime.datetime(0).time()
        morning = (dt >= time(9, 15)) and (dt < time(11, 0))
        afternoon = (dt >= time(13, 0)) and (dt < time(15, 0))
        if not (morning or afternoon): return

        if chop_val < 45:
            self.regime = "TREND"
            # Trend Logic (Confluence)
            # Long
            if self.data.close[0] > self.ema[0] and self.rsi[0] < self.params.conf_rsi_oversold and self.macd.macd[0] > self.macd.signal[0]:
                 self.log(f"Trend Buy (CHOP {chop_val:.1f})")
                 self.buy()
            # Short
            elif self.data.close[0] < self.ema[0] and self.rsi[0] > self.params.conf_rsi_overbought and self.macd.macd[0] < self.macd.signal[0]:
                 self.log(f"Trend Sell (CHOP {chop_val:.1f})")
                 self.sell()
                 
        elif chop_val > 55:
            self.regime = "RANGE"
            # Range Logic (BB Reversion)
            # Long
            if self.data.close[0] < self.bb.lines.bot[0] and self.rsi[0] < 30:
                 self.log(f"Range Buy (CHOP {chop_val:.1f})")
                 self.buy()
            # Short
            elif self.data.close[0] > self.bb.lines.top[0] and self.rsi[0] > 70:
                 self.log(f"Range Sell (CHOP {chop_val:.1f})")
                 self.sell()

def run_strategy():
    store = OAStore()
    df = fetch_and_stitch_data(store, days=200)
    if df is None: return

    cerebro = bt.Cerebro()
    cerebro.addstrategy(AdaptiveRegimeStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    class OAData(bt.feeds.PandasData): pass
    cerebro.adddata(OAData(dataname=df))
    cerebro.broker.setcash(100000.0)
    
    print('Starting Value: %.2f' % cerebro.broker.getvalue())
    results = cerebro.run()
    
    strat = results[0]
    ta = strat.analyzers.trades.get_analysis()
    total = ta.total.closed
    wins = ta.won.total
    rate = (wins/total*100) if total > 0 else 0
    pnl = ta.pnl.net.total
    
    print(f"\n--- Adaptive Regime Strategy Stats ---")
    print(f"Total Trades: {total}")
    print(f"Win Rate: {rate:.2f}%")
    print(f"Net PnL: {pnl:.2f}")

if __name__ == '__main__':
    run_strategy()

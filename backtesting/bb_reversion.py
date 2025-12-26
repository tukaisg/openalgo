import os
import sys
import calendar
from datetime import datetime, timedelta, date, time
import backtrader as bt
import pandas as pd
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Set Environment Variables for OAStore
os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

# Import OAStore
try:
    from openalgo_bt.stores.oa import OAStore
except ImportError:
    pass

# --- Helper Functions for Expiry & Symbols (Reused) ---
SYMBOL_CACHE = {}

def resolve_nifty_symbol(store, year, month):
    mmm = date(year, month, 1).strftime("%b").upper()
    yy = date(year, month, 1).strftime("%y")
    cache_key = f"{mmm}{yy}"
    
    if cache_key in SYMBOL_CACHE:
        return SYMBOL_CACHE[cache_key]

    query = f"NIFTY {mmm} {yy}"
    try:
        response = store.client.search(query=query, exchange="NFO")
        if isinstance(response, dict) and response.get('status') == 'success':
            data = response.get('data', [])
            target_suffix = f"{mmm}{yy}FUT"
            candidates = [i.get('symbol', '') for i in data]
            valid_candidates = [c for c in candidates if c.endswith(target_suffix) and c.startswith("NIFTY") and c[5:7].isdigit()]
            if valid_candidates:
                found = valid_candidates[0]
                SYMBOL_CACHE[cache_key] = found
                return found
    except Exception:
        pass
    return None

def fetch_and_stitch_data(store, days=200):
    end_date_limit = datetime.now()
    start_date_limit = end_date_limit - timedelta(days=days)
    all_dfs = []
    
    print(f"--- Stitching Data for last {days} days ---")
    
    iter_date = start_date_limit.replace(day=1)
    months_to_fetch = []
    while iter_date <= end_date_limit:
        months_to_fetch.append((iter_date.year, iter_date.month))
        iter_date += timedelta(days=32)
        iter_date = iter_date.replace(day=1)
        
    months_to_fetch = sorted(list(set(months_to_fetch)))
    
    last_expiry_date = None
    
    for year, month in months_to_fetch:
        symbol_base = resolve_nifty_symbol(store, year, month)
        if not symbol_base:
            continue
        symbol_full = f"NFO:{symbol_base}"
        
        try:
            date_part = symbol_base[5:12]
            expiry_date_obj = datetime.strptime(date_part, "%d%b%y").date()
        except:
            continue

        fetch_end = min(datetime.combine(expiry_date_obj, datetime.max.time()), end_date_limit)
        
        if last_expiry_date:
             fetch_start = datetime.combine(last_expiry_date + timedelta(days=1), datetime.min.time())
        else:
             fetch_start = start_date_limit
             
        fetch_start = max(fetch_start, start_date_limit)
        
        if fetch_start >= fetch_end:
            last_expiry_date = expiry_date_obj
            continue
            
        print(f"Fetching {symbol_full} ({fetch_start.date()} to {fetch_end.date()})...")
        
        try:
            interval = store.bt_to_interval(bt.TimeFrame.Minutes, 1)
            candles = store.fetch_historical(
                symbol=symbol_full,
                start=fetch_start.strftime("%Y-%m-%d"),
                end_date=(fetch_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval=interval
            )
            
            if candles:
                df = pd.DataFrame(candles)
                rename_map = {'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'}
                df.rename(columns=rename_map, inplace=True)
                
                if 'timestamp' in df.columns:
                    first_val = df['timestamp'].iloc[0]
                    if isinstance(first_val, (int, float)):
                         df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
                    else:
                         df['datetime'] = pd.to_datetime(df['timestamp'])
                
                if 'datetime' in df.columns:
                    df.set_index('datetime', inplace=True)
                    df.sort_index(inplace=True)
                    df = df[(df.index >= fetch_start) & (df.index <= fetch_end)]
                    if not df.empty:
                        all_dfs.append(df)
        except Exception:
            pass

        last_expiry_date = expiry_date_obj

    if not all_dfs:
        return None
        
    final_df = pd.concat(all_dfs)
    final_df.sort_index(inplace=True)
    final_df = final_df[~final_df.index.duplicated(keep='first')]
    return final_df

class BBReversionStrategy(bt.Strategy):
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('rsi_period', 14),
        ('rsi_buy', 30),
        ('rsi_sell', 70),
        ('ema_period', 200),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.params.bb_period, devfactor=self.params.bb_dev)
        self.rsi = bt.indicators.RSI_Safe(self.data.close, period=self.params.rsi_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.params.ema_period)
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            elif order.issell():
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')
        self.order = None

    def next(self):
        if self.order:
            return

        # Time Filter (using approved hours)
        dt = self.datas[0].datetime.datetime(0).time()
        morning = (dt >= time(9, 15)) and (dt < time(11, 0))
        afternoon = (dt >= time(13, 0)) and (dt < time(15, 0))
        can_trade = morning or afternoon

        if not self.position:
            if can_trade:
                # Buy: Price < Lower Band AND RSI < 30 AND Trend is UP (Price > EMA)
                if self.data.close[0] < self.bb.lines.bot[0] and self.rsi[0] < self.params.rsi_buy and self.data.close[0] > self.ema[0]:
                    self.log(f'BUY CREATE (Trend Up), Close: {self.data.close[0]:.2f}, EMA: {self.ema[0]:.2f}')
                    self.order = self.buy()
                
                # Sell: Price > Upper Band AND RSI > 70 AND Trend is DOWN (Price < EMA)
                elif self.data.close[0] > self.bb.lines.top[0] and self.rsi[0] > self.params.rsi_sell and self.data.close[0] < self.ema[0]:
                    self.log(f'SELL CREATE (Trend Down), Close: {self.data.close[0]:.2f}, EMA: {self.ema[0]:.2f}')
                    self.order = self.sell()
        else:
            # Exit Logic
            # If Long: Exit at Middle Band (Mean Reversion)
            if self.position.size > 0:
                if self.data.close[0] >= self.bb.lines.mid[0]:
                    self.log(f'CLOSE LONG (Mean Reverted), Close: {self.data.close[0]:.2f}, Mid: {self.bb.lines.mid[0]:.2f}')
                    self.order = self.close()
            
            # If Short: Exit at Middle Band
            elif self.position.size < 0:
                if self.data.close[0] <= self.bb.lines.mid[0]:
                    self.log(f'CLOSE SHORT (Mean Reverted), Close: {self.data.close[0]:.2f}, Mid: {self.bb.lines.mid[0]:.2f}')
                    self.order = self.close()

def run_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(BBReversionStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    store = OAStore()
    final_df = fetch_and_stitch_data(store, days=200)
    
    if final_df is None or final_df.empty:
        print("No data.")
        return

    class OAData(bt.feeds.PandasData):
        params = (('datetime', None), ('open', 'open'), ('high', 'high'), ('low', 'low'), ('close', 'close'), ('volume', 'volume'), ('openinterest', -1))
    
    cerebro.adddata(OAData(dataname=final_df))
    cerebro.broker.setcash(100000.0)
    
    print('Starting Value: %.2f' % cerebro.broker.getvalue())
    results = cerebro.run()
    
    strat = results[0]
    trade_analysis = strat.analyzers.trades.get_analysis()
    
    wins = trade_analysis.won.total
    total = trade_analysis.total.closed
    win_rate = (wins / total * 100) if total > 0 else 0
    
    print(f"\n--- BB Reversion Stats ---")
    print(f"Total Trades: {total}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net PnL: {trade_analysis.pnl.net.total:.2f}")

if __name__ == '__main__':
    run_strategy()

import os
import sys
import calendar
from datetime import datetime, timedelta, date
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

# --- Helper Functions for Expiry & Symbols ---

# Cache for resolved symbols to avoid repeated API calls
SYMBOL_CACHE = {}

def resolve_nifty_symbol(store, year, month):
    """
    Search and find the correct NIFTY Futures symbol for a specific month/year.
    """
    mmm = date(year, month, 1).strftime("%b").upper()
    yy = date(year, month, 1).strftime("%y")
    cache_key = f"{mmm}{yy}"
    
    if cache_key in SYMBOL_CACHE:
        return SYMBOL_CACHE[cache_key]

    # Search query: "NIFTY MMM YY" or similar. 
    # Try "NIFTY {MMM} {YY}"
    query = f"NIFTY {mmm} {yy}"
    print(f"  ? Searching for contract: {query}")
    
    try:
        # We need access to the inner client of OAStore. 
        # OAStore sets self.client.
        response = store.client.search(query=query, exchange="NFO")
        
        if isinstance(response, dict) and response.get('status') == 'success':
            data = response.get('data', [])
            # Filter for Futures
            # Look for exact pattern NIFTYddMMMyyFUT
            # The day 'dd' is variable (2 chars). 
            # Pattern: NIFTY + 2 digits + MMM + YY + FUT
            target_suffix = f"{mmm}{yy}FUT"
            
            candidates = []
            for item in data:
                sym = item.get('symbol', '')
                if sym.endswith(target_suffix) and sym.startswith("NIFTY"):
                    candidates.append(sym)
            
            # If multiple, take the one that looks like monthly (usually no prefix like 'BANK')
            # The search 'NIFTY' returns BANKNIFTY etc.
            # We want strictly 'NIFTY' prefix (implied Nifty 50).
            # The results showed: 'NIFTY30DEC25FUT'. 
            # So it starts with 'NIFTY' and has digits immediately.
            
            valid_candidates = [c for c in candidates if c.startswith("NIFTY") and c[5:7].isdigit()]
            
            if valid_candidates:
                # If multiple (unlikely for same month except maybe spread contracts?), take first.
                # Actually there's usually only one monthly future per expiry.
                found = valid_candidates[0]
                print(f"    -> Found: {found}")
                SYMBOL_CACHE[cache_key] = found
                return found
    except Exception as e:
        print(f"    -> Search failed: {e}")
        
    return None

def fetch_and_stitch_data(store, days=200):
    """
    Fetch data for the last 'days' by checking which monthly contract was active.
    Stitch them into a single DataFrame.
    """
    end_date_limit = datetime.now()
    start_date_limit = end_date_limit - timedelta(days=days)
    
    # We iterate month by month from start_date_limit to end_date_limit
    
    all_dfs = []
    
    print(f"--- Stitching Data for last {days} days ({start_date_limit.date()} to {end_date_limit.date()}) ---")
    
    # Generate list of months to cover
    months_to_fetch = []
    iter_date = start_date_limit
    
    while iter_date <= end_date_limit:
        months_to_fetch.append((iter_date.year, iter_date.month))
        # Add ~32 days to skip to next month roughly
        iter_date += timedelta(days=32)
        iter_date = iter_date.replace(day=1) # normalize to 1st
    
    # Ensure we cover the end date month too if loop exited early
    if (end_date_limit.year, end_date_limit.month) not in months_to_fetch:
         months_to_fetch.append((end_date_limit.year, end_date_limit.month))

    # Remove duplicates
    months_to_fetch = sorted(list(set(months_to_fetch)))
    
    print(f"Covering months: {months_to_fetch}")

    last_expiry_date = None
    
    for year, month in months_to_fetch:
        # Resolve Symbol
        symbol_base = resolve_nifty_symbol(store, year, month)
        if not symbol_base:
            print(f"Skipping {month}/{year} (No symbol found)")
            continue
            
        symbol_full = f"NFO:{symbol_base}"
        
        # Calculate expiry date from the symbol string to determine fetch end
        # Symbol format: NIFTYddMMMyyFUT. 
        # Extract ddMMMyy -> parse date.
        try:
            # NIFTY is 5 chars.
            # dd is 2 chars.
            # MMM is 3 chars.
            # yy is 2 chars.
            # FUT is 3 chars.
            # Total date part start index 5.
            date_part = symbol_base[5:12] # e.g. 30DEC25
            expiry_date_obj = datetime.strptime(date_part, "%d%b%y").date()
        except ValueError:
            print(f"Could not parse date from {symbol_base}. Skipping.")
            continue

        fetch_end = min(datetime.combine(expiry_date_obj, datetime.max.time()), end_date_limit)
        
        # Start date: Prev expiry + 1, or global start
        if last_expiry_date:
             fetch_start = datetime.combine(last_expiry_date + timedelta(days=1), datetime.min.time())
        else:
             fetch_start = start_date_limit
             
        fetch_start = max(fetch_start, start_date_limit)
        
        if fetch_start >= fetch_end:
            last_expiry_date = expiry_date_obj
            continue
            
        print(f"Fetching {symbol_full} from {fetch_start.date()} to {fetch_end.date()}...")
        
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
                
                if 'datetime' in df.columns:
                     df['datetime'] = pd.to_datetime(df['datetime'])
                elif 'timestamp' in df.columns:
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
                        print(f"  -> Got {len(df)} rows.")
                        all_dfs.append(df)
                    else:
                        print("  -> Empty after filtering.")
                else:
                    print("  -> No datetime column found.")

            else:
                print("  -> No data returned.")
                
        except Exception as e:
            print(f"  -> Error fetching {symbol_full}: {e}")

        last_expiry_date = expiry_date_obj

    if not all_dfs:
        return None
        
    final_df = pd.concat(all_dfs)
    final_df.sort_index(inplace=True)
    final_df = final_df[~final_df.index.duplicated(keep='first')]
    
    print(f"Total Stitched Data: {len(final_df)} rows.")
    return final_df


class ConfluenceStrategy(bt.Strategy):
    params = (
        ('rsi_period', 14),
        ('rsi_overbought', 55),
        ('rsi_oversold', 45), 
        ('ema_period', 200),
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
    )

    def __init__(self):
        # Indicators
        self.rsi = bt.indicators.RSI_Safe(self.data.close, period=self.params.rsi_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.params.ema_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}')
            elif order.issell():
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}')
            
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None

    def next(self):
        if self.order:
            return

        # --- Time Filter ---
        dt = self.datas[0].datetime.datetime(0)
        t = dt.time()
        
        # Active Hours: 09:15 - 11:00 OR 13:00 - 15:00
        # Determine if we are allowed to ENTER trades.
        # We might want to allow EXITS anytime, but strictly entry is filtered.
        
        morning_session = (t >= datetime.strptime("09:15", "%H:%M").time()) and (t < datetime.strptime("11:00", "%H:%M").time())
        afternoon_session = (t >= datetime.strptime("13:00", "%H:%M").time()) and (t < datetime.strptime("15:00", "%H:%M").time())
        
        can_trade = morning_session or afternoon_session
        
        # Current indicator values
        close = self.data.close[0]
        rsi = self.rsi[0]
        ema = self.ema[0]
        macd_line = self.macd.macd[0]
        macd_signal = self.macd.signal[0]

        # Check if we are in the market
        if not self.position:
            if can_trade:
                # LONG Confluence
                if close > ema and rsi < self.params.rsi_oversold and macd_line > macd_signal:
                    self.log(f'BUY CREATE (Confluence), Close: {close:.2f}, EMA: {ema:.2f}, RSI: {rsi:.2f}')
                    self.order = self.buy()
        
        else:
            # SHORT / EXIT Signal
            # We exit if the conditions flip or for profit.
            # Here we follow the Short Confluence logic to reverse/close.
            # NOTE: Exits are usually allowed anytime to protect capital, 
            # OR we can restrict exits to active hours too. 
            # Standard practice: Entries filtered, Exits allowed (stop loss etc). 
            # But here "Short Confluence" is an active short entry logic too.
            
            # Let's assume we can CLOSE anytime if conditions mandate, 
            # or strictly follow the strategy rules for reversal.
            
            # Strategy says "Short if Price < EMA200..." -> this is a Short Entry.
            # If we treat it as just an exit for our Long:
            if close < ema and rsi > self.params.rsi_overbought and macd_line < macd_signal:
                if can_trade: # Only enter new short (or reverse) during active hours
                    self.log(f'SELL CREATE (Confluence), Close: {close:.2f}, EMA: {ema:.2f}, RSI: {rsi:.2f}')
                    self.order = self.sell()
                else:
                    # If we are just closing a long position, maybe we allow it?
                    # For simplicity, respecting the "Trade Only" filter.
                    pass


def run_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ConfluenceStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    store = OAStore()

    # Dynamic Stitching
    final_df = fetch_and_stitch_data(store, days=200)
    
    if final_df is None or final_df.empty:
        print("No data available for backtest.")
        return

    # Create Data Feed
    class OAData(bt.feeds.PandasData):
        params = (
            ('datetime', None),
            ('open', 'open'),
            ('high', 'high'),
            ('low', 'low'),
            ('close', 'close'),
            ('volume', 'volume'),
            ('openinterest', -1),
        )
    
    data = OAData(dataname=final_df)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(100000.0)
    
    print(f'\nStarting Backtest with {len(final_df)} stitched bars...')
    print('Starting Value: %.2f' % cerebro.broker.getvalue())
    results = cerebro.run()
    print('Final Value: %.2f' % cerebro.broker.getvalue())
    
    # Analysis
    strat = results[0]
    trade_analysis = strat.analyzers.trades.get_analysis()
    
    total_trades = trade_analysis.total.open + trade_analysis.total.closed
    won_trades = trade_analysis.won.total
    lost_trades = trade_analysis.lost.total
    win_rate = (won_trades / trade_analysis.total.closed) * 100 if trade_analysis.total.closed > 0 else 0
    
    print("\n--- Confluence Strategy Statistics (Dynamic Symbols + Time Filter) ---")
    print(f"Total Trades: {trade_analysis.total.closed}")
    print(f"Wins: {won_trades} | Losses: {lost_trades}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net PnL:   {trade_analysis.pnl.net.total:.2f}")

if __name__ == '__main__':
    run_strategy()

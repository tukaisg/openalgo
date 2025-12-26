import os
import sys
from datetime import datetime, timedelta
import backtrader as bt
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Set Environment Variables for OAStore
os.environ["OPENALGO_API_KEY"] = os.getenv("OPENALGO_API_KEY")
os.environ["OPENALGO_API_HOST"] = "http://127.0.0.1:5000"

# Import OAStore (ensure path is correct or install package properly)
try:
    from openalgo_bt.stores.oa import OAStore
except ImportError:
    # If openalgo-backtrader is not installed in env, try to add path
    # Assuming standard structure if installed via uv/pip
    pass

class RSIScalpingStrategy(bt.Strategy):
    params = (
        ('rsi_period', 5),
        ('rsi_upper', 80),
        ('rsi_lower', 20),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI_Safe(self.data.close, period=self.params.rsi_period)
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
            
            self.bar_executed = len(self)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None

    def next(self):
        # Simply log the RSI value to verify indicator calculation
        # self.log(f'Close: {self.data.close[0]:.2f}, RSI: {self.rsi[0]:.2f}')

        if self.order:
            return

        # Check if we are in the market
        if not self.position:
            # Buy Signal: RSI < Lower Level (20)
            if self.rsi[0] < self.params.rsi_lower:
                self.log(f'BUY CREATE, RSI: {self.rsi[0]:.2f}')
                self.order = self.buy()
        
        else:
            # Sell Signal (Exit): RSI > Upper Level (80)
            if self.rsi[0] > self.params.rsi_upper:
                self.log(f'SELL CREATE, RSI: {self.rsi[0]:.2f}')
                self.order = self.sell()

def run_strategy():
    cerebro = bt.Cerebro()
    
    # Add Strategy
    cerebro.addstrategy(RSIScalpingStrategy)

    # Add Analyzers
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Initialize OpenAlgo Store
    store = OAStore()
    
    # Define Data Verification
    # Use verified valid symbol
    symbol = "NIFTY30DEC25FUT" # Exchange is handled by OAStore defaults or needs 'NSE:' prefix if auto-detected
    # For OAStore, usually expects "EXCHANGE:SYMBOL" or just SYMBOL if store handles it.
    # Based on test_bt.py success with "NSE:SBIN", and our finding of "NFO" exchange for futures:
    symbol_full = "NFO:NIFTY30DEC25FUT"

    # Fetch 1 Minute data for last 5 days
    now = datetime.now()
    start_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    print(f"Starting Backtest for {symbol_full} (1 Min) [{start_date} to {end_date}]")

    try:
        # 1. Fetch data as Pandas DataFrame
        interval = store.bt_to_interval(bt.TimeFrame.Minutes, 1)
        candles = store.fetch_historical(
            symbol=symbol_full,
            start=start_date,
            end_date=end_date,
            interval=interval
        )
        
        if not candles:
            print("No data fetched from OpenAlgo.")
            return

        # Convert to DataFrame
        import pandas as pd
        df = pd.DataFrame(candles)
        
        # Rename columns to standard names first
        rename_map = {'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'}
        df.rename(columns=rename_map, inplace=True)

        if 'datetime' in df.columns:
            # Already has datetime column, ensure it's index
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)

        elif 'timestamp' in df.columns:
            # Handle potential epoch timestamp
            # OpenAlgo history usually returns epoch seconds or ISO string.
            # If it's a number (int/float), convert it.
            # safe conversion
            first_val = df['timestamp'].iloc[0]
            if isinstance(first_val, (int, float)):
                 df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            else:
                 df['datetime'] = pd.to_datetime(df['timestamp'])
                 
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)
        else:
            print("Error: 'timestamp', 't', or 'datetime' column not found in data.")
            print(f"Columns: {df.columns}")
            return

        # 2. Feed to Cerebro using PandasData
        # Define Data Feed Class to map columns if needed
        class OAData(bt.feeds.PandasData):
            params = (
                ('datetime', None), # inferred from index
                ('open', 'open'),
                ('high', 'high'),
                ('low', 'low'),
                ('close', 'close'),
                ('volume', 'volume'),
                ('openinterest', -1),
            )
        
        data = OAData(dataname=df)
        cerebro.adddata(data)
        
        # Set initial cash
        cerebro.broker.setcash(100000.0)
        
        # Run
        print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
        results = cerebro.run()
        print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
        
        # Print Trade Analysis
        strat = results[0]
        trade_analysis = strat.analyzers.trades.get_analysis()
        
        total_trades = trade_analysis.total.open + trade_analysis.total.closed
        won_trades = trade_analysis.won.total
        lost_trades = trade_analysis.lost.total
        win_rate = (won_trades / trade_analysis.total.closed) * 100 if trade_analysis.total.closed > 0 else 0
        
        print("\n--- Strategy Statistics ---")
        print(f"Total Trades: {trade_analysis.total.closed} (Open: {trade_analysis.total.open})")
        print(f"Wins: {won_trades} | Losses: {lost_trades}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Gross PnL: {trade_analysis.pnl.gross.total:.2f}")
        print(f"Net PnL:   {trade_analysis.pnl.net.total:.2f}")
        
    except Exception as e:
        print(f"Backtest Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    run_strategy()

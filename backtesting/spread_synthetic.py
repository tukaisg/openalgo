import pandas as pd
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
LOT_SIZE = 50
INITIAL_CAPITAL = 70000  # Updated Capital
SPREAD_WIDTH = 200      # Distance between ATM and OTM Strike
ATM_DELTA = 0.50
OTM_DELTA = 0.30        # Estimated Delta for Strike+200
THETA_DECAY_ATM = 5     # Points per day (Simulated)
THETA_DECAY_OTM = 3     # Points per day (Simulated)

import sys
import os

# Allow importing from current directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from backtesting.confluence_strategy import fetch_and_stitch_data
    from openalgo_bt.stores.oa import OAStore
except ImportError as e:
    logging.error(f"Import Error: {e}")
    sys.exit(1)

def get_data_from_store():
    """Fetch data using OAStore"""
    store = OAStore()
    df = fetch_and_stitch_data(store, days=60) # Test 60 days
    if df is not None:
        # DF from store is already indexed by datetime (hopefully) or needs inspection
        # fetch_and_stitch_data returns a dataframe with 'open', 'high', 'low', 'close', 'volume'
        # and index as datetime.
        # We need to resample it from 1min (default) to 5min for logic.
        
        # Ensure index is datetime
        if not isinstance(df.index, pd.DatetimeIndex):
             df.index = pd.to_datetime(df.index)
        
        df_resampled = df.resample('5min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        return df_resampled
    return None

def calculate_indicators(df):
    """Calculate Strategy Indicators"""
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # MACD
    exp12 = df['close'].ewm(span=12, adjust=False).mean()
    exp26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

def simulate_spread_backtest(df):
    """Simulate Bull Call / Bear Put Spreads"""
    
    capital = INITIAL_CAPITAL
    position = None # 'LONG_SPREAD' or 'SHORT_SPREAD'
    entry_price_fut = 0
    entry_price_atm = 0
    entry_price_otm = 0
    trades = []
    
    # Time Filters
    start_time = pd.Timestamp("09:15").time()
    end_time = pd.Timestamp("15:00").time()
    no_trade_start = pd.Timestamp("11:00").time()
    no_trade_end = pd.Timestamp("13:00").time()

    for i in range(200, len(df)):
        curr_bar = df.iloc[i]
        prev_bar = df.iloc[i-1]
        timestamp = curr_bar.name.time()
        
        # --- Time Filter ---
        if timestamp < start_time or timestamp > end_time:
            # Force Close End of Day
            if position:
                exit_price_fut = curr_bar['close']
                move = exit_price_fut - entry_price_fut
                
                # Synthetic Option Pricing Logic
                # Bull Spread: Buy ATM, Sell OTM
                # Net Delta = 0.5 - 0.3 = 0.2
                
                if position == 'BULL_SPREAD': # ATM Call Long, OTM Call Short
                    pnl_long = move * ATM_DELTA
                    pnl_short = -(move * OTM_DELTA) # If market Up, Short Call loses
                    net_pnl_pts = pnl_long + pnl_short - (THETA_DECAY_ATM - THETA_DECAY_OTM) # Net Theta Decay
                    
                elif position == 'BEAR_SPREAD': # ATM Put Long, OTM Put Short
                    pnl_long = -move * ATM_DELTA     # Market Down = Profit
                    pnl_short = -(-move * OTM_DELTA) # Market Down = Short Put Loses
                    net_pnl_pts = pnl_long + pnl_short - (THETA_DECAY_ATM - THETA_DECAY_OTM)

                pnl_real = net_pnl_pts * LOT_SIZE
                capital += pnl_real
                trades.append({
                    'type': position,
                    'entry_time': str(entry_time),
                    'exit_time': str(curr_bar.name),
                    'net_pts': net_pnl_pts,
                    'pnl': pnl_real
                })
                position = None
            continue

        if no_trade_start <= timestamp <= no_trade_end:
            continue

        # --- Strategy Logic (Confluence) ---
        long_cond = (curr_bar['close'] > curr_bar['EMA_200']) and \
                    (curr_bar['MACD'] > curr_bar['Signal_Line']) and \
                    (curr_bar['RSI'] > 55)
                    
        short_cond = (curr_bar['close'] < curr_bar['EMA_200']) and \
                     (curr_bar['MACD'] < curr_bar['Signal_Line']) and \
                     (curr_bar['RSI'] < 45)

        # Entry
        if position is None:
            if long_cond:
                position = 'BULL_SPREAD'
                entry_price_fut = curr_bar['close']
                entry_time = curr_bar.name
            elif short_cond:
                position = 'BEAR_SPREAD'
                entry_price_fut = curr_bar['close']
                entry_time = curr_bar.name
        
        # Exit (Opposite Signal or SL/TP - simplified to signal/EOD here)
        elif position == 'BULL_SPREAD' and short_cond:
             # Close Logic (Copy-Paste from EOD for now, refactor later)
            exit_price_fut = curr_bar['close']
            move = exit_price_fut - entry_price_fut
            pnl_long = move * ATM_DELTA
            pnl_short = -(move * OTM_DELTA)
            net_pnl_pts = pnl_long + pnl_short - 0.5 # Small intraday decay
            
            pnl_real = net_pnl_pts * LOT_SIZE
            capital += pnl_real
            trades.append({'type': 'BULL_SPREAD', 'net_pts': net_pnl_pts, 'pnl': pnl_real})
            position = None
            
        elif position == 'BEAR_SPREAD' and long_cond:
            exit_price_fut = curr_bar['close']
            move = exit_price_fut - entry_price_fut
            pnl_long = -move * ATM_DELTA
            pnl_short = -(-move * OTM_DELTA)
            net_pnl_pts = pnl_long + pnl_short - 0.5
            
            pnl_real = net_pnl_pts * LOT_SIZE
            capital += pnl_real
            trades.append({'type': 'BEAR_SPREAD', 'net_pts': net_pnl_pts, 'pnl': pnl_real})
            position = None

    return trades, capital

if __name__ == "__main__":
    df = get_data_from_store()
    if df is not None:
        df = calculate_indicators(df)
        trades, final_cap = simulate_spread_backtest(df)
        
        print(f"Initial Capital: {INITIAL_CAPITAL}")
        print(f"Final Capital: {final_cap:.2f}")
        print(f"Total Trades: {len(trades)}")
        
        wins = [t for t in trades if t['pnl'] > 0]
        print(f"Win Rate: {len(wins)/len(trades)*100:.2f}%" if trades else "Win Rate: 0%")
        
        # Save to CSV for analysis
        pd.DataFrame(trades).to_csv('spread_backtest_results.csv')

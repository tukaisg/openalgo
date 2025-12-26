import os
import sys
import backtrader as bt
from dotenv import load_dotenv

# Allow importing from current directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from backtesting.confluence_strategy import ConfluenceStrategy, fetch_and_stitch_data
    from openalgo_bt.stores.oa import OAStore
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def run_synthetic_option_backtest():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ConfluenceStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    store = OAStore()

    # Reuse the same Data Stitching Logic
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
    
    # Capital (Not strictly used for synthetic calculation but good for Margin check failure prevention)
    cerebro.broker.setcash(100000.0) 
    # Sizer: 1 Unit of Future -> PnL = Points
    cerebro.addsizer(bt.sizers.FixedSize, stake=1)

    print(f'\n[Synthetic Option Buying] Starting Backtest on Futures Data...')
    results = cerebro.run()
    
    # Analysis
    strat = results[0]
    trade_analysis = strat.analyzers.trades.get_analysis()
    
    # Extract Trade List
    # trade_analysis.total.closed gives count.
    # trade_analysis doesn't give list of trades easily in dictionary format unless we dig.
    # Actually, Backtrader TradeAnalyzer summary is high level.
    # We might need to iterate through strategy.orders? No, strat._trades usually holds them.
    
    # Let's rely on the summary PnL (Net Total) which is "Total Points Captured" on Futures.
    futures_points_pnl = trade_analysis.pnl.net.total
    total_trades = trade_analysis.total.closed
    won_trades = trade_analysis.won.total
    lost_trades = trade_analysis.lost.total
    win_rate = (won_trades / total_trades) * 100 if total_trades > 0 else 0
    
    # Synthetic Conversions
    # Delta for ATM Option ~ 0.5
    DELTA = 0.5
    LOT_SIZE = 75
    COST_PER_TRADE = 10 # Brokerage etc.
    THETA_PENALTY_POINTS = 5 # Approx decay/slippage points per trade
    
    # Calculation
    # Option Points = Futures Points * Delta
    # But wait, we must apply Theta Penalty per trade.
    
    # To do this accurately, we need per-trade PnL.
    # 'pnl.net.total' is sum of all trades.
    # Let's estimate:
    # Total Option Points = (Futures Points * Delta) - (Total Trades * THETA_PENALTY_POINTS)
    
    synthetic_option_points = (futures_points_pnl * DELTA) - (total_trades * THETA_PENALTY_POINTS)
    synthetic_option_pnl_inr = synthetic_option_points * LOT_SIZE
    
    # Adjust for Brokerage (₹50 per order -> ₹100 per trade * Total Trades)
    net_inr = synthetic_option_pnl_inr #- (total_trades * 100) # Optional
    
    print("\n" + "="*60)
    print("RESUlTS: Synthetic Option Buying Logic (Based on Futures)")
    print("="*60)
    print(f"Underlying:       NIFTY Futures (Stitched)")
    print(f"Strategy:         Confluence (Trend Following)")
    print(f"Simulation:       ATM Option Buy (Delta {DELTA})")
    print(f"Assumed Penalty:  {THETA_PENALTY_POINTS} points/trade (Theta + Slippage)")
    print("-" * 60)
    
    print(f"Total Trades:     {total_trades}")
    print(f"Win Rate (Fut):   {win_rate:.2f}%")
    print(f"Futures PnL:      {futures_points_pnl:.2f} points")
    print("-" * 60)
    print(f"Syn. Option Ppts: {synthetic_option_points:.2f} points")
    print(f"Syn. Lot Size:    {LOT_SIZE}")
    print(f"ESTIMATED PnL:    ₹{net_inr:.2f}")
    print("="*60)
    
    # ROI Calculation
    # Capital needed for Option Buying: ~₹15,000 per lot (ATM 200 * 75)
    CAPITAL_REQUIRED = 15000
    roi = (net_inr / CAPITAL_REQUIRED) * 100
    print(f"Est. ROI (on ₹15k): {roi:.2f}%")

if __name__ == '__main__':
    run_synthetic_option_backtest()

# Hedged Option Strategies - Brainstorming
**Capital Available:** ~₹70,000
**Goal:** Reduce risk/cost compared to Naked Option Buying, or profit from non-directional moves.

## 1. Bull Call Spread / Bear Put Spread (Debit Spreads) - **RECOMMENDED**
- **Structure:** 
    - **Bull:** BUY ATM Call + SELL OTM Call (Higher Strike)
    - **Bear:** BUY ATM Put + SELL OTM Put (Lower Strike)
- **Logic:** You pay a premium for the ATM, but collect premium from the OTM. This *reduces* your cost basis.
- **Pros:**
    - **Cheaper:** Costs less than naked buying.
    - **Theta Protection:** The sold option decays, offsetting some decay of the bought option.
    - **Vol Crush Protection:** If IV drops, the short leg profits, cushioning the long leg's loss.
- **Cons:**
    - **Capped Profit:** You strictly limited upside (max profit = width of spread - cost).
- **Capital:** ~₹25k-₹30k per lot (margin requirement for the short leg is reduced due to the long leg hedge).
- **Suitability:** Perfect fit for the current **Confluence Bot** (Trend Following).

## 2. Long Straddle / Strangle
- **Structure:** BUY ATM Call + BUY ATM Put.
- **Logic:** Profit if the market moves *significantly* in EITHER direction.
- **Pros:** Unlimited profit potential; no directional bias needed.
- **Cons:**
    - **Expensive:** Paying double premium.
    - **Theta Risk:** Massive decay if market stays flat (Chop = Death).
- **Capital:** ~₹15k-₹20k (pure buying).
- **Suitability:** Good for "News Events" or "Breakouts", but risky for daily automated trading without strict chop filters.

## 3. Iron Butterfly (Credit Strategy)
- **Structure:** SELL ATM Call + SELL ATM Put (Short Straddle) + BUY OTM Wings (Hedges).
- **Logic:** Profit from time decay in a range-bound market.
- **Pros:** High win rate in choppy markets. Defined risk.
- **Cons:** 
    - **Management:** Requires active adjusting if price tests the wings.
    - **Profit:** Max profit is collected premium, which can be small relative to risk if not managed.
- **Capital:** ~₹40k-₹50k per lot (approx, with hedge benefit).
- **Suitability:** Good complement to the Trend Bot (run this when Trend Bot is OFF).

## 4. Calendar Spreads (Time Hedges)
- **Structure:** SELL Near-Week Option + BUY Next-Week Option (Same Strike).
- **Logic:** Near-week decays faster than Next-week.
- **Pros:** Low margin, positive Theta.
- **Cons:** Very sensitive to IV changes (Vega risk). Hard to backtest synthetically without full option chain data.

---

# Selection for Backtesting
Given the current setup (Confluence Strategy = Trend Following) and capital (~₹70k), **Debit Spreads (Strategy #1)** are the best upgrade.

## Hypothesis for Backtest
- **Strategy:** Confluence Signal (Trend).
- **Execution:** Instead of just `BUY ATM`, we will simulate `BUY ATM + SELL OTM (Strike + 100)`.
- **Expected Outcome:** Lower win rate (maybe?) but smoother equity curve and less drawdown than naked buying.

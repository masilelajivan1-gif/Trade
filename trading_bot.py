"""
Starter stock trading bot — moving average crossover on Alpaca PAPER trading.

Strategy: buy when the 20-day SMA crosses above the 50-day SMA,
sell when it crosses back below. Checks once per hour while the market is open.

Setup:
    pip install alpaca-py pandas
    export ALPACA_API_KEY="your_paper_key"
    export ALPACA_SECRET_KEY="your_paper_secret"
    python trading_bot.py

Kill switch: create a file named STOP in the same folder and the bot exits.
"""

import os
import time
import logging
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from alpaca.common.exceptions import APIError

# ---------------- Settings ----------------
SYMBOLS = ["AAPL", "MSFT", "SPY"]
FAST_WINDOW = 20
SLOW_WINDOW = 50
POSITION_PCT = 0.10        # put at most 10% of equity in any one stock
DAILY_LOSS_LIMIT = 0.02    # stop trading for the day if equity drops 2%
CHECK_EVERY_SECONDS = 3600
PAPER = True               # keep True until you've tested thoroughly
# ------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]

trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def get_signal(symbol):
    """Return 'buy', 'sell', or None based on an SMA crossover."""
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.now() - timedelta(days=SLOW_WINDOW * 2 + 30),
        feed=DataFeed.IEX,  # free data feed
    )
    bars = data.get_stock_bars(request).df
    if bars.empty or len(bars) < SLOW_WINDOW + 1:
        log.warning(f"{symbol}: not enough data")
        return None

    close = bars.loc[symbol]["close"]
    fast = close.rolling(FAST_WINDOW).mean()
    slow = close.rolling(SLOW_WINDOW).mean()

    crossed_up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    crossed_down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]

    if crossed_up:
        return "buy"
    if crossed_down:
        return "sell"
    return None


def current_qty(symbol):
    try:
        return float(trading.get_open_position(symbol).qty)
    except APIError:
        return 0.0  # no position


def last_price(symbol):
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=datetime.now() - timedelta(days=3),
        feed=DataFeed.IEX,
    )
    return float(data.get_stock_bars(request).df.loc[symbol]["close"].iloc[-1])


def hit_daily_loss_limit():
    account = trading.get_account()
    equity, start = float(account.equity), float(account.last_equity)
    drawdown = (start - equity) / start
    if drawdown >= DAILY_LOSS_LIMIT:
        log.warning(f"Daily loss limit hit ({drawdown:.2%}). No trades today.")
        return True
    return False


def place_order(symbol, qty, side):
    order = MarketOrderRequest(
        symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY
    )
    trading.submit_order(order)
    log.info(f"ORDER {side.value.upper()} {qty} {symbol}")


def run_once():
    if hit_daily_loss_limit():
        return
    equity = float(trading.get_account().equity)

    for symbol in SYMBOLS:
        try:
            signal = get_signal(symbol)
            held = current_qty(symbol)
            log.info(f"{symbol}: signal={signal} held={held}")

            if signal == "buy" and held == 0:
                qty = int((equity * POSITION_PCT) // last_price(symbol))
                if qty > 0:
                    place_order(symbol, qty, OrderSide.BUY)
            elif signal == "sell" and held > 0:
                place_order(symbol, held, OrderSide.SELL)
        except Exception as e:
            log.error(f"{symbol}: error {e}")


def main():
    log.info(f"Bot starting (paper={PAPER}) on {SYMBOLS}")
    while True:
        if os.path.exists("STOP"):
            log.info("STOP file found. Exiting.")
            break
        if trading.get_clock().is_open:
            run_once()
        else:
            log.info("Market closed.")
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()

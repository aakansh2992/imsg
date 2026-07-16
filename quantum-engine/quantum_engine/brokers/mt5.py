"""MetaTrader 5 adapter (optional, live-capable).

This talks to a real broker via the ``MetaTrader5`` Python package, which only
runs on Windows with the MT5 terminal installed. It is an OPTIONAL dependency:
importing this module without the package raises a clear error, and the rest of
the framework runs fine without it.

⚠️  LIVE TRADING RISK ⚠️
Enabling this backend can place real orders with real money. It is disabled
unless you explicitly pass ``allow_live=True``. Read the README's risk section
first. Start on a demo account. The authors provide no warranty and accept no
liability for losses — see LICENSE.
"""

from __future__ import annotations

from typing import Optional

from ..types import AccountState, Fill, Order, OrderType, Position, Side
from .base import BrokerAdapter

try:  # pragma: no cover - environment dependent
    import MetaTrader5 as mt5  # type: ignore
    _HAS_MT5 = True
except Exception:  # pragma: no cover
    mt5 = None  # type: ignore
    _HAS_MT5 = False


class MT5Broker(BrokerAdapter):
    def __init__(
        self,
        symbol: str = "XAUUSD",
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        allow_live: bool = False,
        contract_size: float = 100.0,
        deviation: int = 20,
    ):
        if not _HAS_MT5:
            raise RuntimeError(
                "MetaTrader5 package not installed. This adapter only works on "
                "Windows with the MT5 terminal. Use SimulatedBroker for paper "
                "trading and backtesting."
            )
        if not allow_live:
            raise RuntimeError(
                "Refusing to initialise a live broker adapter without "
                "allow_live=True. This is a safety gate: real orders can lose "
                "real money. Read the README risk section and use a DEMO "
                "account first."
            )
        self.symbol = symbol
        self.login = login
        self.password = password
        self.server = server
        self.contract_size = contract_size
        self.deviation = deviation

    def connect(self) -> None:  # pragma: no cover - requires live terminal
        kwargs = {}
        if self.login is not None:
            kwargs = {"login": self.login, "password": self.password,
                      "server": self.server}
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    def disconnect(self) -> None:  # pragma: no cover
        mt5.shutdown()

    def account(self) -> AccountState:  # pragma: no cover
        info = mt5.account_info()
        pos = self.position()
        return AccountState(balance=info.balance, equity=info.equity,
                            positions=[pos] if pos else [])

    def position(self) -> Optional[Position]:  # pragma: no cover
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return None
        p = positions[0]
        side = Side.BUY if p.type == mt5.POSITION_TYPE_BUY else Side.SELL
        return Position(symbol=self.symbol, side=side, size=p.volume,
                        entry_price=p.price_open, stop_loss=p.sl or None,
                        take_profit=p.tp or None)

    def submit(self, order: Order) -> Fill:  # pragma: no cover
        tick = mt5.symbol_info_tick(self.symbol)
        price = tick.ask if order.side is Side.BUY else tick.bid
        order_type = (mt5.ORDER_TYPE_BUY if order.side is Side.BUY
                      else mt5.ORDER_TYPE_SELL)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": order.size,
            "type": order_type,
            "price": price,
            "deviation": self.deviation,
            "sl": order.stop_loss or 0.0,
            "tp": order.take_profit or 0.0,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order rejected: {result.retcode} {result.comment}")
        from datetime import datetime
        return Fill(order=order, price=result.price, timestamp=datetime.utcnow())

    def close(self, price: Optional[float] = None) -> Optional[Fill]:  # pragma: no cover
        pos = self.position()
        if pos is None:
            return None
        tick = mt5.symbol_info_tick(self.symbol)
        exit_side = pos.side.opposite
        exit_price = tick.bid if pos.side is Side.BUY else tick.ask
        order_type = (mt5.ORDER_TYPE_SELL if pos.side is Side.BUY
                      else mt5.ORDER_TYPE_BUY)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": pos.size,
            "type": order_type,
            "price": exit_price,
            "deviation": self.deviation,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 close rejected: {result.retcode} {result.comment}")
        from datetime import datetime
        close_order = Order(symbol=self.symbol, side=exit_side, size=pos.size,
                            order_type=OrderType.MARKET)
        return Fill(order=close_order, price=result.price, timestamp=datetime.utcnow())

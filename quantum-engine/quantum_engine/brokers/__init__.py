from .base import BrokerAdapter
from .simulated import SimulatedBroker

__all__ = ["BrokerAdapter", "SimulatedBroker"]

# MT5Broker is imported lazily because it depends on the optional MetaTrader5
# package and is a live-capable adapter. Import it explicitly when you need it:
#     from quantum_engine.brokers.mt5 import MT5Broker

"""The predefined algorithms. Each is written only against `hq`, the same API uploaded code gets."""

from app.algos.api import Strategy
from app.algos.library.bollinger_reversion import BollingerReversion
from app.algos.library.crypto_volatility_breakout import CryptoVolatilityBreakout
from app.algos.library.donchian_breakout import DonchianBreakout
from app.algos.library.rsi_reversion import RsiReversion
from app.algos.library.sma_crossover import SmaCrossover

LIBRARY: dict[str, type[Strategy]] = {
    "sma_crossover": SmaCrossover,
    "rsi_reversion": RsiReversion,
    "donchian_breakout": DonchianBreakout,
    "bollinger_reversion": BollingerReversion,
    "crypto_volatility_breakout": CryptoVolatilityBreakout,
}

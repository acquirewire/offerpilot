"""Exchange layer: a Boost -> live ExchangeQuote (best lay price + liquidity).

Each client implements `quote(event, market, selection) -> ExchangeQuote | None`.
The monitor fans a boost out to every enabled client and hands the results to
rating.best_of, which keeps the exchange giving the best rating.

Status: clients carry the REAL API endpoints and auth flow but are NOT yet
live-tested — they need your credentials (see README). The offline `demo`/`rate`
path exercises the same rating code without them.
"""
from .base import Exchange

__all__ = ["Exchange"]

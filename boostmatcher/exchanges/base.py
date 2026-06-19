"""Common interface + selection-matching glue for exchange clients."""
from __future__ import annotations

from typing import Protocol

from ..matcher import best_runner
from ..models import ExchangeQuote


class Exchange(Protocol):
    name: str
    commission: float

    async def quote(self, event: str, market: str, selection: str) -> ExchangeQuote | None:
        """Best lay price + liquidity for `selection`, or None if not found/laid."""
        ...


def pick_lay(
    name: str, commission: float, runners: dict[str, tuple],
    selection: str, *, market_id: str | None = None,
) -> ExchangeQuote | None:
    """Shared tail end of every client: given a {runner: (lay, liq[, back])} map
    for a resolved market, match the boost selection to a runner, build the quote.
    The optional 3rd element (best back price) feeds value mode's fair midpoint.
    """
    runner = best_runner(selection, list(runners))
    if runner is None:
        return None
    vals = runners[runner]
    lay_odds, available = vals[0], vals[1]
    back = vals[2] if len(vals) > 2 else None
    return ExchangeQuote(exchange=name, lay_odds=lay_odds, available=available,
                         commission=commission, runner=runner, market_id=market_id,
                         back_odds=back)

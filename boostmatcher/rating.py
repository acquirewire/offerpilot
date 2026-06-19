"""The rating core: turn a boost + exchange quote into locked-profit maths.

All matched-betting boost value comes from one equation. You BACK £S at the
boosted price B, then LAY the same selection on an exchange at price L (which
charges commission c on the lay's net winnings). The lay stake that makes your
profit identical whether the selection wins or loses is:

    lay_stake = (B * S) / (L - c)

With that lay stake:

    profit_if_back_wins  = S*(B-1)            # bookie pays out
                         - lay_stake*(L-1)    #   minus exchange liability
    profit_if_back_loses = lay_stake*(1-c)    # exchange lay cashes (after comm)
                         - S                   #   minus the lost back stake

By construction those two are equal — that equal figure is the guaranteed lock.
When B is boosted well above the true price both are POSITIVE: free money. When
the boost is smaller you may keep a value bet with one slightly-negative leg.

The "rating" is locked profit as a % of stake: rating 8.0 means a £10 back
nets ~£0.80 risk-free. Anything >= 0 is at worst break-even with +EV upside.
Pure functions, stdlib only — this module is the part that decides where money
goes, so it is unit-tested to the penny and has no I/O.
"""
from __future__ import annotations

from .models import Boost, ExchangeQuote, RatedBoost


def compute_lay(
    back_stake: float, back_odds: float, lay_odds: float, commission: float
) -> tuple[float, float, float, float]:
    """Return (lay_stake, liability, profit_if_back_wins, profit_if_back_loses).

    Uses the equal-profit lay stake. `commission` is the exchange's rate on net
    lay winnings as a fraction (Smarkets 0.02, Betfair ~0.05 default/0.02 disc).
    """
    if lay_odds <= 1.0:
        raise ValueError(f"lay_odds must be > 1.0, got {lay_odds}")
    if not 0.0 <= commission < 1.0:
        raise ValueError(f"commission must be in [0,1), got {commission}")

    lay_stake = (back_odds * back_stake) / (lay_odds - commission)
    liability = lay_stake * (lay_odds - 1.0)

    profit_if_wins = back_stake * (back_odds - 1.0) - liability
    profit_if_loses = lay_stake * (1.0 - commission) - back_stake
    return lay_stake, liability, profit_if_wins, profit_if_loses


def rate(boost: Boost, quote: ExchangeQuote, back_stake: float) -> RatedBoost:
    """Rate one boost against one exchange quote at the given back stake."""
    lay_stake, liability, p_win, p_lose = compute_lay(
        back_stake, boost.boosted_odds, quote.lay_odds, quote.commission
    )
    locked = min(p_win, p_lose)            # the guaranteed figure (equal in theory)
    rated = RatedBoost(
        boost=boost,
        quote=quote,
        back_stake=back_stake,
        lay_stake=round(lay_stake, 2),
        liability=round(liability, 2),
        profit_if_wins=round(p_win, 2),
        profit_if_loses=round(p_lose, 2),
        rating=round(100.0 * locked / back_stake, 3),
    )

    # Liquidity sanity: you can only lay up to what backers are offering.
    if quote.available < liability:
        rated.notes.append(
            f"thin: only GBP{quote.available:.0f} available vs GBP{liability:.0f} liability needed"
        )
    if boost.max_stake is not None and back_stake > boost.max_stake:
        rated.notes.append(f"stake GBP{back_stake:.0f} exceeds boost cap GBP{boost.max_stake:.0f}")
    if boost.original_odds:
        # Crude value check vs the pre-boost price (treats original as ~fair):
        edge = 100.0 * (boost.boosted_odds / boost.original_odds - 1.0)
        rated.notes.append(f"+{edge:.0f}% vs pre-boost price")
    return rated


def best_of(boost: Boost, quotes: list[ExchangeQuote], back_stake: float) -> RatedBoost:
    """Rate a boost across several exchanges; keep the highest-rating quote.

    Returns an unrated RatedBoost (quote=None) if no quotes were supplied, so
    callers can still surface a boost they couldn't match for manual laying.
    """
    rateds = [rate(boost, q, back_stake) for q in quotes]
    if not rateds:
        return RatedBoost(boost=boost, quote=None, back_stake=back_stake,
                          notes=["no exchange match -- lay manually"])
    return max(rateds, key=lambda r: r.rating)

"""gembets — find football (soccer) "gem bets": value bets and statistically
mispriced odds, then push them to your phone via ntfy.

Two independent detectors feed one notifier:

  * Detector A (outlier.py)   -- pure market maths. De-vig every book's prices
                                 to a margin-free consensus, then flag any book
                                 pricing an outcome materially above that fair
                                 value. No model, no extra data: highest ROI,
                                 lowest effort, ship first.
  * Detector B (statedge.py)  -- statistical mispricing. Turn a real-world rate
                                 (a fullback's fouls conceded /90, a referee's
                                 cards /game) into a probability via a Poisson
                                 model and compare it to the book's implied
                                 price. Higher edge, scarcer data, more noise.

Mirrors the boostmatcher/jobtracker layout: pure-stdlib maths core (odds.py),
dataclass models, API layers stubbed behind keys (odds_api/stats_api), an async
scrape->detect->alert loop (monitor.py), and notify reuse (same .env as the
Fatsoma/jobtracker bots). You place every bet manually — this only finds them.
"""

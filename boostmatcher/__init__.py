"""boostmatcher — find and rate +EV bookmaker price boosts ("superboosts").

A boost is matched-betting-profitable when the BOOSTED back price at a bookie
beats the LAY price on an exchange by enough to clear the exchange commission.
This package monitors bookie boost pages, pulls live exchange lay prices, and
ranks every boost by how much of your stake the lay locks in (the "rating").

Mirrors the jobtracker layout: scrapers (raw page -> Boost), an exchange layer
(Boost -> live lay quote), a pure rating core (the EV maths), and notify reuse.
"""

"""
competition.py
Supply-vs-demand feasibility check for the Solo Barber Digital Twin.

Every prior version of this model (Revision 1 AND Revision 2) assumed Will's
180-client book, walk-in rate, and 84% chair utilization transfer identically
to all 100 cities, regardless of how many other barbers/barbershops already
compete for the same clientele in that market. This module grounds a rough
but real supply/demand check in published industry data so the "true
take-home" ranking can be checked against whether the underlying demand
actually exists.

DATA SOURCES (approximate, directional -- not authoritative micro-data):
- IBISWorld "Barber Shops in the US" (2025): ~154,925 barbershops nationally,
  ~176,672 people employed in the industry, ~$7.0B market size.
- Business-directory scrape (poidata/rentechdigital, 2026): state-level shop
  counts used ONLY for relative state-to-state density comparison (its
  absolute national total differs from IBISWorld's, so it is rescaled below).
- Industry visit-frequency surveys: men average ~6-9 barbershop/salon visits
  per year; short-fade maintenance clients (Will's target segment) cut more
  often, on a ~28-day cycle (~13/yr), consistent with the rest of this model.

These are city-proper population estimates and rough demographic/frequency
assumptions -- treat the output as a directional plausibility screen, not a
market-research-grade forecast.
"""

from typing import Dict

# --- National industry baseline (IBISWorld 2025) ---
NATIONAL_POPULATION = 335_000_000
NATIONAL_BARBERSHOPS = 154_925
NATIONAL_PEOPLE_PER_SHOP = NATIONAL_POPULATION / NATIONAL_BARBERSHOPS  # ~2,163
AVG_BARBERS_PER_SHOP = 176_672 / 154_925  # ~1.14 -- most US barbershops are solo/two-chair operations

# Revenue-per-worker ($7.0B / 176,672 employees =~ $39.6k) divided by a
# blended industry-average ticket price (~$35, lower than Will's $38-65 menu
# since it spans budget shops too) implies a typical incumbent barber's
# annual cut volume -- NOT Will's aggressive near-max-utilization pace.
_INDUSTRY_REVENUE_PER_WORKER = 7_000_000_000 / 176_672
_BLENDED_INDUSTRY_TICKET = 35.0
AVG_CUTS_PER_BARBER_PER_YEAR = _INDUSTRY_REVENUE_PER_WORKER / _BLENDED_INDUSTRY_TICKET  # ~1,130/yr

# Share of a city's total population that are "barbershop patrons" (men who
# prefer a barbershop cut over a salon or self-cut): ~50% male population x
# ~60% adult share x ~50% barbershop-preference share.
BARBERSHOP_PATRON_SHARE = 0.15

# Blended annual visit frequency across a market's full patron mix (national
# survey average ~6-9/yr, pulled up somewhat by fade-maintenance regulars).
ANNUAL_VISITS_PER_PATRON = 9.0

# --- State-level relative shop density (derived from directory data) ---
# Directory-scrape state counts: CA 14,753 | TX 14,339 | FL 9,321 shops.
# Their implied national total (109,589) differs from IBISWorld's more
# authoritative 154,925, so we use these ONLY to compute each state's
# density *relative to that same source's national average*, then rescale
# that relative multiplier onto the IBISWorld national baseline above.
_DIRECTORY_STATE_SHOPS = {"CA": 14_753, "TX": 14_339, "FL": 9_321}
_DIRECTORY_STATE_POPULATION = {"CA": 39_000_000, "TX": 31_000_000, "FL": 23_000_000}
_DIRECTORY_NATIONAL_TOTAL_SHOPS = 109_589
_DIRECTORY_NATIONAL_POPULATION = NATIONAL_POPULATION
_DIRECTORY_NATIONAL_PEOPLE_PER_SHOP = _DIRECTORY_NATIONAL_POPULATION / _DIRECTORY_NATIONAL_TOTAL_SHOPS

STATE_PEOPLE_PER_SHOP: Dict[str, float] = {"DEFAULT": NATIONAL_PEOPLE_PER_SHOP}
for _state, _shops in _DIRECTORY_STATE_SHOPS.items():
    _state_people_per_shop = _DIRECTORY_STATE_POPULATION[_state] / _shops
    _relative_density = _DIRECTORY_NATIONAL_PEOPLE_PER_SHOP / _state_people_per_shop
    STATE_PEOPLE_PER_SHOP[_state] = NATIONAL_PEOPLE_PER_SHOP / _relative_density


def people_per_shop(state: str) -> float:
    return STATE_PEOPLE_PER_SHOP.get(state, STATE_PEOPLE_PER_SHOP["DEFAULT"])


# Two assumption sets, not one point estimate. The central case uses this
# module's derived constants; the conservative case asks "what if fewer
# people patronize barbershops than assumed, AND existing incumbents already
# operate as efficiently as Will's aggressive near-max-utilization pace?"
# Reporting both is the honest answer to "is there really enough demand" --
# a single-scenario verdict here would be false precision.
_SCENARIOS = {
    "central": {"patron_share": BARBERSHOP_PATRON_SHARE, "visits_per_patron": ANNUAL_VISITS_PER_PATRON,
                "cuts_per_barber": AVG_CUTS_PER_BARBER_PER_YEAR},
    "conservative": {"patron_share": 0.10, "visits_per_patron": 7.0, "cuts_per_barber": 1900.0},
}


def _run_scenario(city_population: int, state: str, wills_annual_cuts: float, scenario: dict) -> dict:
    existing_shops = city_population / people_per_shop(state)
    market_supply_cuts = existing_shops * AVG_BARBERS_PER_SHOP * scenario["cuts_per_barber"]
    market_demand_cuts = city_population * scenario["patron_share"] * scenario["visits_per_patron"]

    supply_saturation_pct = (market_supply_cuts / market_demand_cuts * 100.0) if market_demand_cuts > 0 else float("inf")
    wills_market_share_pct = (wills_annual_cuts / market_demand_cuts * 100.0) if market_demand_cuts > 0 else float("inf")

    return {
        "existing_shops_est": existing_shops,
        "market_demand_cuts_est": market_demand_cuts,
        "market_supply_cuts_est": market_supply_cuts,
        "supply_saturation_pct": supply_saturation_pct,
        "wills_market_share_pct": wills_market_share_pct,
    }


def assess_market_feasibility(city_population: int, state: str, wills_annual_cuts: float) -> dict:
    """
    Estimates local barbershop supply & demand under both a central and a
    conservative assumption set, and reports the resulting range -- rather
    than a single categorical "feasible / not feasible" verdict that would
    overstate how precisely this can be known from available industry data.
    """
    central = _run_scenario(city_population, state, wills_annual_cuts, _SCENARIOS["central"])
    conservative = _run_scenario(city_population, state, wills_annual_cuts, _SCENARIOS["conservative"])

    sat_lo, sat_hi = sorted([central["supply_saturation_pct"], conservative["supply_saturation_pct"]])
    share_lo, share_hi = sorted([central["wills_market_share_pct"], conservative["wills_market_share_pct"]])

    if sat_lo >= 105.0:
        feasibility = "Saturated in both scenarios - requires displacing incumbents"
    elif sat_hi < 100.0:
        feasibility = "Headroom in both scenarios"
    else:
        feasibility = "Sensitive to assumptions - ranges from headroom to saturated"

    return {
        "existing_shops_est": central["existing_shops_est"],
        "central_supply_saturation_pct": central["supply_saturation_pct"],
        "conservative_supply_saturation_pct": conservative["supply_saturation_pct"],
        "saturation_pct_range": (sat_lo, sat_hi),
        "wills_market_share_pct_range": (share_lo, share_hi),
        "feasibility": feasibility,
    }

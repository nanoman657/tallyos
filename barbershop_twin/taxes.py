"""
taxes.py
Shared federal/self-employment tax logic for the Solo Barber Digital Twin.

Previously, every simulator in this package (simulation.py, simulate_markets.py,
simulate_top_100_cities.py) computed "true take-home cash" as:
    pretax_profit - SE_tax - state_city_tax
with NO federal income tax whatsoever. For a sole-proprietor LLC, Schedule C net
profit is also subject to ordinary federal income tax (after the QBI deduction
and the standard deduction), which materially changes every result. This module
centralizes that calculation so all simulators use the same, correct logic.

2024 tax year figures (IRS Rev. Proc. 2023-34). Single-parent operator files
Head of Household by default.
"""

from typing import Literal

FilingStatus = Literal["single", "head_of_household"]

# (bracket_ceiling, marginal_rate) — last bracket ceiling is effectively infinite
FEDERAL_BRACKETS_2024 = {
    "single": [
        (11_600, 0.10),
        (47_150, 0.12),
        (100_525, 0.22),
        (191_950, 0.24),
        (243_725, 0.32),
        (609_350, 0.35),
        (float("inf"), 0.37),
    ],
    "head_of_household": [
        (16_550, 0.10),
        (63_100, 0.12),
        (100_500, 0.22),
        (191_950, 0.24),
        (243_700, 0.32),
        (609_350, 0.35),
        (float("inf"), 0.37),
    ],
}

STANDARD_DEDUCTION_2024 = {
    "single": 14_600.0,
    "head_of_household": 21_900.0,
}

# IRC Sec. 199A: 20% deduction on Qualified Business Income. Below the phase-in
# threshold ($191,950 single / HoH for 2024), the wage/UBIA limitation and the
# specified-service-trade exclusion don't apply, and barbering is not an SSTB
# anyway, so a flat 20% of QBI (capped at 20% of taxable income before QBI) is
# an accurate approximation at the income levels this model produces.
QBI_RATE = 0.20

SE_TAX_RATE = 0.153
SE_TAX_INCOME_FRACTION = 0.9235  # IRC Sec. 1402(a) — 92.35% of net SE earnings


def self_employment_tax(net_profit: float) -> float:
    """FICA/Medicare SE tax on Schedule C net profit (IRC Sec. 1401)."""
    return max(0.0, net_profit * SE_TAX_INCOME_FRACTION * SE_TAX_RATE)


def _apply_brackets(taxable_income: float, filing_status: FilingStatus) -> float:
    brackets = FEDERAL_BRACKETS_2024[filing_status]
    tax = 0.0
    prev_ceiling = 0.0
    for ceiling, rate in brackets:
        if taxable_income <= prev_ceiling:
            break
        slice_amount = min(taxable_income, ceiling) - prev_ceiling
        tax += slice_amount * rate
        prev_ceiling = ceiling
    return tax


def federal_income_tax(
    net_profit: float,
    se_tax: float,
    health_insurance_annual: float = 0.0,
    filing_status: FilingStatus = "head_of_household",
) -> float:
    """
    Computes federal ordinary income tax on Schedule C net profit, accounting for:
      - the above-the-line deduction for one-half of SE tax
      - the above-the-line self-employed health insurance premium deduction
      - the standard deduction
      - the Sec. 199A Qualified Business Income (QBI) deduction
    """
    if net_profit <= 0:
        return 0.0

    agi = net_profit - (se_tax / 2.0) - health_insurance_annual
    agi = max(0.0, agi)

    standard_deduction = STANDARD_DEDUCTION_2024[filing_status]
    taxable_before_qbi = max(0.0, agi - standard_deduction)

    qbi_base = max(0.0, net_profit - (se_tax / 2.0))
    qbi_deduction = min(QBI_RATE * qbi_base, QBI_RATE * taxable_before_qbi)

    taxable_income = max(0.0, taxable_before_qbi - qbi_deduction)
    return _apply_brackets(taxable_income, filing_status)


def compute_true_take_home(
    pretax_business_profit: float,
    state_city_tax_rate: float,
    health_insurance_annual: float = 6_000.0,
    filing_status: FilingStatus = "head_of_household",
) -> dict:
    """
    Full annual tax waterfall from Schedule C net profit to true spendable cash.
    Health insurance premiums are a real cash outflow (and a federal AGI
    deduction) but are NOT deductible against SE tax or state wage tax, matching
    actual self-employed health insurance deduction rules.
    """
    se_tax = self_employment_tax(pretax_business_profit)
    state_city_tax = max(0.0, pretax_business_profit * state_city_tax_rate)
    fed_tax = federal_income_tax(
        pretax_business_profit, se_tax, health_insurance_annual, filing_status
    )

    true_take_home = (
        pretax_business_profit
        - se_tax
        - state_city_tax
        - fed_tax
        - health_insurance_annual
    )

    return {
        "se_tax": se_tax,
        "state_city_tax": state_city_tax,
        "federal_income_tax": fed_tax,
        "health_insurance_annual": health_insurance_annual,
        "total_tax": se_tax + state_city_tax + fed_tax,
        "true_take_home": true_take_home,
    }

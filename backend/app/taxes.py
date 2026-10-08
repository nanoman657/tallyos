"""
Federal / self-employment tax waterfall for a sole-proprietor barbershop.

Ported unchanged in substance from barbershop_twin/taxes.py (the digital-twin
research code at the repo root) so the ERP's finance screen and the twin's
take-home numbers agree. 2024 tax year (IRS Rev. Proc. 2023-34).
"""

from typing import Literal

FilingStatus = Literal["single", "head_of_household"]

FEDERAL_BRACKETS_2024 = {
    "single": [
        (11_600, 0.10), (47_150, 0.12), (100_525, 0.22), (191_950, 0.24),
        (243_725, 0.32), (609_350, 0.35), (float("inf"), 0.37),
    ],
    "head_of_household": [
        (16_550, 0.10), (63_100, 0.12), (100_500, 0.22), (191_950, 0.24),
        (243_700, 0.32), (609_350, 0.35), (float("inf"), 0.37),
    ],
}
STANDARD_DEDUCTION_2024 = {"single": 14_600.0, "head_of_household": 21_900.0}
QBI_RATE = 0.20                 # IRC Sec. 199A; barbering is not an SSTB
SE_TAX_RATE = 0.153
SE_TAX_INCOME_FRACTION = 0.9235  # IRC Sec. 1402(a)


def self_employment_tax(net_profit: float) -> float:
    return max(0.0, net_profit * SE_TAX_INCOME_FRACTION * SE_TAX_RATE)


def _apply_brackets(taxable_income: float, filing_status: FilingStatus) -> float:
    tax, prev = 0.0, 0.0
    for ceiling, rate in FEDERAL_BRACKETS_2024[filing_status]:
        if taxable_income <= prev:
            break
        tax += (min(taxable_income, ceiling) - prev) * rate
        prev = ceiling
    return tax


def federal_income_tax(net_profit: float, se_tax: float, health_insurance_annual: float = 0.0,
                       filing_status: FilingStatus = "head_of_household") -> float:
    if net_profit <= 0:
        return 0.0
    agi = max(0.0, net_profit - se_tax / 2.0 - health_insurance_annual)
    taxable_before_qbi = max(0.0, agi - STANDARD_DEDUCTION_2024[filing_status])
    qbi_base = max(0.0, net_profit - se_tax / 2.0)
    qbi_deduction = min(QBI_RATE * qbi_base, QBI_RATE * taxable_before_qbi)
    return _apply_brackets(max(0.0, taxable_before_qbi - qbi_deduction), filing_status)


def compute_true_take_home(pretax_business_profit: float, state_city_tax_rate: float,
                           health_insurance_annual: float = 6_000.0,
                           filing_status: FilingStatus = "head_of_household") -> dict:
    se_tax = self_employment_tax(pretax_business_profit)
    state_city_tax = max(0.0, pretax_business_profit * state_city_tax_rate)
    fed_tax = federal_income_tax(pretax_business_profit, se_tax, health_insurance_annual, filing_status)
    return {
        "se_tax": se_tax,
        "state_city_tax": state_city_tax,
        "federal_income_tax": fed_tax,
        "health_insurance_annual": health_insurance_annual,
        "total_tax": se_tax + state_city_tax + fed_tax,
        "true_take_home": pretax_business_profit - se_tax - state_city_tax - fed_tax - health_insurance_annual,
    }

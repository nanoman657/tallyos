"""
simulate_startup_costs.py
1-CHAIR SOLO BARBERSHOP STARTUP CAPITAL & ROI ANALYSIS (100 U.S. CITIES)
Calculates:
1. Rent Security Deposit (2 Months Rent)
2. Equipment & Furniture (Hydraulic Chair, Towel Warmer, Steamer, Station, Mirror)
3. Professional Tools & Initial Consumables Inventory
4. State/City Licensing, Permits & Liability Insurance
5. Branding, Vinyl Decals & Launch Marketing
6. Total Initial Capital Required & Payback Period (Months to 100% ROI)
"""

import os
import pandas as pd

# Will's 180 existing regulars live in Houston and don't relocate with him.
# Any other market means rebuilding a client book from a cold start, so payback
# there can't assume day-one steady-state utilization the way Houston can.
HOME_MARKET = "Houston, TX"
RAMP_UP_FACTORS = [0.25, 0.50, 0.75]  # months 1-3 of a new market; month 4+ = 1.0


def calculate_payback_months(total_startup_cost: float, monthly_take_home_steady: float, is_home_market: bool) -> float:
    """
    Months of cumulative take-home cash needed to recoup startup capital.
    Home market (Houston) starts at full steady-state utilization since Will's
    existing client base is already there. Every other market ramps up over
    the first 3 months while a new client book is built.
    """
    if monthly_take_home_steady <= 0:
        return float("inf")
    if is_home_market:
        return total_startup_cost / monthly_take_home_steady

    cumulative = 0.0
    month = 0
    monthly_factors = RAMP_UP_FACTORS + [1.0] * 24  # cap search at 27 months
    while cumulative < total_startup_cost and month < len(monthly_factors):
        cumulative += monthly_take_home_steady * monthly_factors[month]
        month += 1
        if cumulative >= total_startup_cost:
            # Fractional month within this period
            overshoot = cumulative - total_startup_cost
            this_month_amount = monthly_take_home_steady * monthly_factors[month - 1]
            fraction_unneeded = overshoot / this_month_amount if this_month_amount > 0 else 0.0
            return month - fraction_unneeded
    return float(month)


def calculate_startup_costs():
    df_cities = pd.read_csv("/root/research/barbershop_twin/results/top_100_cities_results.csv")
    
    startup_results = []
    
    for idx, row in df_cities.iterrows():
        city_name = row["city"]
        state = row["state"]
        monthly_lease = row["lease_annual"] / 12.0 - 200.0 # Extract pure lease portion
        monthly_take_home = row["take_home"] / 12.0
        
        # 1. Lease Security Deposit (First month + Security Deposit = 2 months rent)
        lease_deposit = monthly_lease * 2.0
        
        # 2. Equipment & Furniture (Calibrated to regional vendor delivery / local costs)
        # High-cost metros (NYC, SF, LA, Seattle) have slightly higher delivery & installation costs
        is_metro_high = monthly_lease >= 2200.0
        is_metro_mid = 1600.0 <= monthly_lease < 2200.0
        
        equip_base = 2800.0 if is_metro_high else (2400.0 if is_metro_mid else 2000.0)
        
        # 3. Professional Tools & Initial Supplies Inventory
        tools_inventory = 1200.0
        
        # 4. Licensing, Permits, State Board Fees & Insurance
        # States like CA, NY, PA, MA, DC have higher municipal licensing & board inspection fees
        if state in ["CA", "NY", "PA", "MA", "DC", "HI"]:
            licensing_insurance = 850.0
        elif state in ["TX", "FL", "AZ", "TN", "NV", "WA"]:
            licensing_insurance = 550.0
        else:
            licensing_insurance = 650.0
            
        # 5. Branding, Suite Decals & Initial Launch Marketing
        marketing_branding = 750.0
        
        # Total Capital Required
        total_startup_cost = lease_deposit + equip_base + tools_inventory + licensing_insurance + marketing_branding

        is_home_market = (city_name == HOME_MARKET)

        # Payback Period in Months: Houston starts at full steady-state utilization
        # (existing 180-client book); every other market ramps up over 3 months
        # while a new client base is built from scratch.
        payback_months = calculate_payback_months(total_startup_cost, monthly_take_home, is_home_market)

        # First-Year Return on Capital (ROC %), ramp-adjusted for non-home markets
        if is_home_market:
            first_year_take_home = row["take_home"]
        else:
            ramp_months_take_home = sum(monthly_take_home * f for f in RAMP_UP_FACTORS)
            steady_months_take_home = monthly_take_home * (12 - len(RAMP_UP_FACTORS))
            first_year_take_home = ramp_months_take_home + steady_months_take_home
        first_year_roc = (first_year_take_home / total_startup_cost) * 100.0

        startup_results.append({
            "city": city_name,
            "state": state,
            "monthly_lease": monthly_lease,
            "lease_deposit": lease_deposit,
            "equipment_furniture": equip_base,
            "tools_supplies": tools_inventory,
            "licensing_insurance": licensing_insurance,
            "marketing_decal": marketing_branding,
            "total_startup_cost": total_startup_cost,
            "take_home_annual": row["take_home"],
            "take_home_monthly": monthly_take_home,
            "payback_months": payback_months,
            "first_year_roc": first_year_roc
        })
        
    df_startup = pd.DataFrame(startup_results)
    
    # Sort by Fastest Payback Period (Highest ROC)
    df_by_roi = df_startup.sort_values(by="payback_months", ascending=True).reset_index(drop=True)
    df_by_roi.to_csv("/root/research/barbershop_twin/results/startup_costs_analysis.csv", index=True)
    
    print("=" * 100)
    print(" 🚀 TOP 10 CITIES WITH FASTEST STARTUP ROI (PAYBACK PERIOD IN MONTHS)")
    print("    1-Chair Suite Setup | Lease Deposit + Equipment + Licensing + Inventory")
    print("=" * 100)
    print(f"{'Rank':<4} | {'City, State':<22} | {'Startup Capital':<15} | {'Annual Take-Home':<17} | {'Payback Period':<15} | {'1st-Yr ROC %'}")
    print("-" * 100)
    for i in range(10):
        row = df_by_roi.iloc[i]
        print(f"#{i+1:<3} | {row['city']:<22} | ${row['total_startup_cost']:<14,.0f} | ${row['take_home_annual']:<16,.2f} | {row['payback_months']:<5.1f} months      | {row['first_year_roc']:.1f}%")
    print("=" * 100)
    
    print("\n🏙️ STARTUP COSTS IN TOP METROS (NYC, SF, Miami, Houston, LA, Chicago, Philly):")
    print("-" * 100)
    target_cities = ["San Francisco, CA", "Miami, FL", "New York, NY", "Austin, TX", "Houston, TX", "Los Angeles, CA", "Philadelphia, PA", "Chicago, IL"]
    df_targets = df_startup[df_startup["city"].isin(target_cities)].sort_values(by="total_startup_cost", ascending=False)
    for _, row in df_targets.iterrows():
        print(f"• {row['city']:<20} | Startup Capital: ${row['total_startup_cost']:<8,.0f} | (Lease Deposit: ${row['lease_deposit']:,.0f} + Equip: ${row['equipment_furniture']:,.0f}) | Payback: {row['payback_months']:.1f} mos")
    print("=" * 100)

if __name__ == "__main__":
    calculate_startup_costs()

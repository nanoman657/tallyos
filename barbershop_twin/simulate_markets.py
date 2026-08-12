"""
simulate_markets.py
INSTITUTIONAL-GRADE GEOGRAPHIC MARKET DIGITAL TWIN FOR SOLO BARBER WILL
Calibrated directly to Will's Live Booksy Menu at Fresh & Focused Barbershop LLC (2855 Mangum Rd, Houston, TX 77092):
- Standard Cuts / Skin Fades: $38.00 avg ($35 - $40 menu)
- Fresh Combo (Hair/Beard/Razor/Steam): $65.00 avg ($60 combo + $25 steam wash / facial add-ons)
- Physical Capacity Ceiling: 12 standard cuts/day (40 min) OR 8 Fresh Combos/day (60 min)
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from taxes import federal_income_tax

def run_tethered_simulation(market_name: str, config: dict, days: int = 365) -> dict:
    np.random.seed(42)
    
    base_price = config["base_price"]       # $38.00 (Fresh Cut / Skin Fade)
    bundle_price = config["bundle_price"]   # $65.00 (Fresh Combo + Steam Wash / Facial)
    monthly_suite_lease = config["monthly_suite_lease"]
    monthly_software_ins = config["monthly_software_ins"]
    state_city_tax_rate = config["state_city_tax_rate"]
    is_philly_winter = config["is_philly_winter"]
    walkin_poisson_avg = config["walkin_poisson_avg"]
    bundle_receptivity = config["bundle_receptivity"]
    health_insurance_annual = config.get("health_insurance_annual", 6000.0)
    filing_status = config.get("filing_status", "head_of_household")

    open_days_per_year = 245
    total_weekdays = 260

    total_annual_overhead = (monthly_suite_lease + monthly_software_ins) * 12.0
    daily_overhead_rate = total_annual_overhead / float(total_weekdays)

    # PHYSICAL CAPACITY CEILING BASED ON MINUTES:
    # Total workday = 480 minutes (8 hours), minus a mandatory 30-min lunch/reset
    # break that isn't bookable chair time -> 450 usable minutes.
    # Standard Cut ($38) takes 40 mins -> max 11 cuts/day.
    # Fresh Combo ($65) takes 60 mins -> max 7 combos/day.
    max_daily_minutes = 480 - 30
    min_per_standard = 40
    min_per_combo = 60
    
    current_clients = 180
    
    cc_processing_rate = 0.030
    cogs_standard_cut = 1.80  # Neck strip, clipper spray, cape laundry, blades
    cogs_bundle = 3.20        # Fresh razor blade, hot towel, steam water, beard oil, balm
    
    total_gross_rev = 0.0
    total_cc_fees = 0.0
    total_cogs = 0.0
    total_fixed_oh = 0.0
    
    total_cuts = 0
    total_bundles = 0
    total_turnaways = 0
    total_minutes_worked = 0
    
    daily_records = []
    days_worked_so_far = 0
    
    for day in range(1, days + 1):
        day_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][(day - 1) % 7]
        
        if day_of_week in ["Mon", "Sun"]:
            daily_records.append({
                "day": day, "revenue": 0.0, "take_home": 0.0, "utilization": 0.0, "cuts": 0, "is_open": False, "reason": "Weekend Off"
            })
            continue
            
        is_winter_period = is_philly_winter and (day <= 60 or day >= 335)
        is_severe_snowstorm = is_winter_period and (np.random.random() < 0.12)
        
        if is_severe_snowstorm:
            total_fixed_oh += daily_overhead_rate
            daily_records.append({
                "day": day, "revenue": 0.0, "take_home": -daily_overhead_rate, "utilization": 0.0, "cuts": 0, "is_open": False, "reason": "Snow Closure"
            })
            continue

        if days_worked_so_far >= open_days_per_year or (np.random.random() < (15.0 / 260.0)):
            total_fixed_oh += daily_overhead_rate
            daily_records.append({
                "day": day, "revenue": 0.0, "take_home": -daily_overhead_rate, "utilization": 0.0, "cuts": 0, "is_open": False, "reason": "PTO/Sick"
            })
            continue
            
        days_worked_so_far += 1
        
        weather_mod = 1.0
        beard_mod = 1.0
        is_winter_slush_day = is_winter_period and not is_severe_snowstorm and (np.random.random() < 0.40)
        
        if is_winter_slush_day:
            weather_mod = 0.35 
        else:
            if not is_philly_winter and (150 <= day <= 250): beard_mod = 1.25
            if np.random.random() < 0.15: weather_mod = 0.70
                
        is_peak_day = day_of_week in ["Fri", "Sat"]
        effective_bundle_receptivity = min(0.85, bundle_receptivity * (1.40 if is_peak_day else 1.0))

        base_demand = (current_clients / 28.0) * weather_mod * beard_mod
        walkins = np.random.poisson(walkin_poisson_avg if is_peak_day else max(1, walkin_poisson_avg - 1))
        walkins = int(walkins * weather_mod)
        total_demand_clients = int(round(base_demand + walkins))
        
        # TIME-CAPACITY YIELD MANAGEMENT LOOP:
        # We fill Will's 480 daily minutes. On peak days, we prioritize Fresh Combos ($65, 60m).
        day_standard = 0
        day_bundles = 0
        day_mins = 0
        
        # Calculate how many of the demand want Fresh Combos vs Standard Cuts
        desired_bundles = int(round(total_demand_clients * (effective_bundle_receptivity * beard_mod)))
        desired_standard = max(0, total_demand_clients - desired_bundles)
        
        if is_peak_day:
            # Book Fresh Combos first!
            while desired_bundles > 0 and (day_mins + min_per_combo) <= max_daily_minutes:
                day_bundles += 1
                day_mins += min_per_combo
                desired_bundles -= 1
            while desired_standard > 0 and (day_mins + min_per_standard) <= max_daily_minutes:
                day_standard += 1
                day_mins += min_per_standard
                desired_standard -= 1
        else:
            # Book Standard Cuts first on weekdays, then combos
            while desired_standard > 0 and (day_mins + min_per_standard) <= max_daily_minutes:
                day_standard += 1
                day_mins += min_per_standard
                desired_standard -= 1
            while desired_bundles > 0 and (day_mins + min_per_combo) <= max_daily_minutes:
                day_bundles += 1
                day_mins += min_per_combo
                desired_bundles -= 1
                
        unserved = desired_bundles + desired_standard
        if unserved > 0:
            total_turnaways += unserved
            
        actual_cuts = day_standard + day_bundles
        day_gross_rev = (day_standard * base_price) + (day_bundles * bundle_price)
        day_cc_fee = day_gross_rev * cc_processing_rate
        day_cogs = (day_standard * cogs_standard_cut) + (day_bundles * cogs_bundle)
        
        total_gross_rev += day_gross_rev
        total_cc_fees += day_cc_fee
        total_cogs += day_cogs
        total_fixed_oh += daily_overhead_rate
        
        total_cuts += actual_cuts
        total_bundles += day_bundles
        total_minutes_worked += day_mins
        
        # Daily utilization is time-based (minutes worked / 480 mins)
        daily_util_pct = (day_mins / float(max_daily_minutes)) * 100.0
        
        daily_records.append({
            "day": day, "revenue": day_gross_rev, "take_home": 0.0, "utilization": daily_util_pct, "cuts": actual_cuts, "is_open": True, "reason": "Open"
        })
        
    df = pd.DataFrame(daily_records)
    open_df = df[df["is_open"] == True]
    actual_days_worked = len(open_df)
    
    total_fixed_oh = total_annual_overhead
    total_pre_tax_profit = total_gross_rev - total_cc_fees - total_cogs - total_fixed_oh

    total_se_tax = max(0.0, (total_pre_tax_profit * 0.9235) * 0.153)
    total_state_city_tax = max(0.0, total_pre_tax_profit * state_city_tax_rate)
    total_federal_tax = federal_income_tax(
        total_pre_tax_profit, total_se_tax, health_insurance_annual, filing_status
    )
    total_true_take_home = (
        total_pre_tax_profit - total_se_tax - total_state_city_tax
        - total_federal_tax - health_insurance_annual
    )

    # Tethered Time Utilization % = Total Minutes Worked / (Actual Days Worked * 480 mins)
    tethered_utilization = (total_minutes_worked / (actual_days_worked * max_daily_minutes)) * 100.0
    
    # Federal tax + health insurance are non-linear/annual, so they're prorated across
    # open days by revenue share purely for the cumulative take-home chart.
    lump_sum = total_federal_tax + health_insurance_annual
    for idx, row in df.iterrows():
        if row["is_open"]:
            day_rev = row["revenue"]
            day_cc = day_rev * cc_processing_rate
            day_cogs = day_rev * (total_cogs / max(1.0, total_gross_rev))
            day_pre = day_rev - day_cc - day_cogs - daily_overhead_rate
            day_se = max(0.0, (day_pre * 0.9235) * 0.153)
            day_state = max(0.0, day_pre * state_city_tax_rate)
            day_lump_share = (day_rev / total_gross_rev) * lump_sum if total_gross_rev > 0 else 0.0
            df.at[idx, "take_home"] = day_pre - day_se - day_state - day_lump_share

    summary = {
        "market": market_name,
        "days_worked": actual_days_worked,
        "total_gross_rev": total_gross_rev,
        "total_cc_fees": total_cc_fees,
        "total_cogs": total_cogs,
        "total_fixed_overhead": total_fixed_oh,
        "total_pretax_profit": total_pre_tax_profit,
        "total_se_tax": total_se_tax,
        "total_state_city_tax": total_state_city_tax,
        "total_federal_tax": total_federal_tax,
        "total_health_insurance": health_insurance_annual,
        "total_true_take_home": total_true_take_home,
        "tethered_utilization": tethered_utilization,
        "aov": total_gross_rev / max(1, total_cuts),
        "total_cuts": total_cuts,
        "total_bundles": total_bundles,
        "total_turnaways": total_turnaways,
        "daily_df": df
    }
    return summary

def run_tethered_comparison():
    print("=" * 96)
    print(" 💈  WILL'S LIVE BOOKSY DIGITAL TWIN (Fresh & Focused Barbershop LLC, Houston TX)")
    print("     Calibrated to Actual Menu: $38 Skin Fades/Cuts | $65 Fresh Combos (Hair/Beard/Steam)")
    print("=" * 96)

    # Cypress TX calibrated to Will's real Booksy prices ($38 cut, $65 combo)
    cypress_config = {
        "base_price": 38.0, "bundle_price": 65.0, "monthly_suite_lease": 1400.0,
        "monthly_software_ins": 200.0, "state_city_tax_rate": 0.0,
        "is_philly_winter": False, "walkin_poisson_avg": 2, "bundle_receptivity": 0.35
    }

    # Philly PA calibrated to urban pricing ($48 cut, $80 combo)
    philly_config = {
        "base_price": 48.0, "bundle_price": 80.0, "monthly_suite_lease": 2166.0,
        "monthly_software_ins": 200.0, "state_city_tax_rate": 0.0682,
        "is_philly_winter": True, "walkin_poisson_avg": 4, "bundle_receptivity": 0.40
    }

    c = run_tethered_simulation("Cypress, TX (Will's Live Booksy)", cypress_config)
    p = run_tethered_simulation("Philadelphia, PA (Winter Studio)", philly_config)

    print(f"\n{'Line Item / Operational Metric':<36} | {'Cypress, TX (Live Menu)':<26} | {'Philadelphia, PA (Winter Adj)':<26}")
    print("-" * 94)
    print(f"{'Days Actually Worked (after PTO/Snow)':<36} | {c['days_worked']} days{'':<18} | {p['days_worked']} days (6 snow closures)")
    print(f"{'Physical Capacity Ceiling (450m/day)':<36} | 11 Cuts (40m) | 7 Combos (60m) | 11 Cuts (40m) | 7 Combos (60m)")
    print("-" * 94)
    print(f"{'Gross Service Revenue':<36} | ${c['total_gross_rev']:<25,.2f} | ${p['total_gross_rev']:<25,.2f}")
    print(f"{'(-) Credit Card Fees (3% Booksy Biz)':<36} | -${c['total_cc_fees']:<24,.2f} | -${p['total_cc_fees']:<24,.2f}")
    print(f"{'(-) Consumables / COGS ($1.80|$3.20)':<36} | -${c['total_cogs']:<24,.2f} | -${p['total_cogs']:<24,.2f}")
    print(f"{'(-) Fixed Suite Lease ($1400|$2166+200)':<36} | -${c['total_fixed_overhead']:<24,.2f} | -${p['total_fixed_overhead']:<24,.2f}")
    print("-" * 94)
    print(f"{'Net Operating Profit (Pre-Tax)':<36} | ${c['total_pretax_profit']:<25,.2f} | ${p['total_pretax_profit']:<25,.2f}")
    print(f"{'(-) Federal SE Tax (15.3% FICA)':<36} | -${c['total_se_tax']:<24,.2f} | -${p['total_se_tax']:<24,.2f}")
    print(f"{'(-) Federal Income Tax (HoH brackets)':<36} | -${c['total_federal_tax']:<24,.2f} | -${p['total_federal_tax']:<24,.2f}")
    print(f"{'(-) State & City Wage Taxes':<36} | -${c['total_state_city_tax']:<24,.2f} | -${p['total_state_city_tax']:<24,.2f}")
    print(f"{'(-) Self-Employed Health Insurance':<36} | -${c['total_health_insurance']:<24,.2f} | -${p['total_health_insurance']:<24,.2f}")
    print("-" * 94)
    print(f"{'⭐ TRUE SPENDABLE TAKE-HOME PAY':<36} | ${c['total_true_take_home']:<25,.2f} | ${p['total_true_take_home']:<25,.2f}")
    print("-" * 94)
    print(f"{'Average Order Value (AOV)':<36} | ${c['aov']:<25.2f} | ${p['aov']:<25.2f}")
    print(f"{'Time-Based Chair Utilization %':<36} | {c['tethered_utilization']:<25.1f}% | {p['tethered_utilization']:<25.1f}%")
    print(f"{'Total Clients Served (Cuts/Combos)':<36} | {c['total_cuts']:<25,d} | {p['total_cuts']:<25,d}")
    print(f"{'Fresh Combos Sold ($65|$80 60-min)':<36} | {c['total_bundles']:<25,d} | {p['total_bundles']:<25,d}")
    print("=" * 94)

    os.makedirs("/root/research/barbershop_twin/results", exist_ok=True)
    df_c = c["daily_df"]
    df_p = p["daily_df"]
    plt.figure(figsize=(12, 6))
    plt.plot(df_c["day"], df_c["take_home"].cumsum(), label="Cypress, TX (Will's Live Booksy Menu)", color="#10b981", linewidth=3)
    plt.plot(df_p["day"], df_p["take_home"].cumsum(), label="Philadelphia, PA (Winter-Adjusted Studio)", color="#3b82f6", linewidth=3)
    plt.title("Spendable Take-Home Pay ($) Calibrated to Will's Live Booksy Menu ($38 Cuts / $65 Combos)", fontsize=13, fontweight="bold")
    plt.xlabel("Day of Year", fontsize=12)
    plt.ylabel("Cumulative True Spendable Take-Home ($)", fontsize=12)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig("/root/research/barbershop_twin/results/institutional_comparison.png", dpi=300)
    plt.close()
    print("\n✅ Institutional comparison chart generated in /root/research/barbershop_twin/results/institutional_comparison.png")

if __name__ == "__main__":
    run_tethered_comparison()

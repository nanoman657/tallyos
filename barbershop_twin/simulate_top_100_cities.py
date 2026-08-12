"""
simulate_top_100_cities.py
"""
import os
import numpy as np
import pandas as pd
from taxes import federal_income_tax
from competition import assess_market_feasibility

# Approximate city-proper population (2023-ish estimates) -- used only to
# scale the supply/demand feasibility screen in competition.py. Not census-
# grade precision; adequate for a directional plausibility check.
CITY_POPULATIONS = {
    ("New York", "NY"): 8_260_000, ("Los Angeles", "CA"): 3_820_000, ("Chicago", "IL"): 2_660_000,
    ("Houston", "TX"): 2_300_000, ("Phoenix", "AZ"): 1_650_000, ("Philadelphia", "PA"): 1_550_000,
    ("San Antonio", "TX"): 1_470_000, ("San Diego", "CA"): 1_380_000, ("Dallas", "TX"): 1_300_000,
    ("San Jose", "CA"): 970_000, ("Austin", "TX"): 970_000, ("Jacksonville", "FL"): 970_000,
    ("Fort Worth", "TX"): 950_000, ("Columbus", "OH"): 910_000, ("Charlotte", "NC"): 900_000,
    ("Indianapolis", "IN"): 880_000, ("San Francisco", "CA"): 810_000, ("Seattle", "WA"): 740_000,
    ("Denver", "CO"): 715_000, ("Oklahoma City", "OK"): 690_000, ("Nashville", "TN"): 690_000,
    ("El Paso", "TX"): 680_000, ("Washington", "DC"): 680_000, ("Las Vegas", "NV"): 660_000,
    ("Boston", "MA"): 650_000, ("Portland", "OR"): 630_000, ("Louisville", "KY"): 625_000,
    ("Memphis", "TN"): 620_000, ("Detroit", "MI"): 620_000, ("Baltimore", "MD"): 570_000,
    ("Milwaukee", "WI"): 560_000, ("Albuquerque", "NM"): 560_000, ("Tucson", "AZ"): 545_000,
    ("Fresno", "CA"): 545_000, ("Sacramento", "CA"): 525_000, ("Mesa", "AZ"): 510_000,
    ("Kansas City", "MO"): 510_000, ("Atlanta", "GA"): 500_000, ("Omaha", "NE"): 485_000,
    ("Colorado Springs", "CO"): 480_000, ("Raleigh", "NC"): 470_000, ("Virginia Beach", "VA"): 460_000,
    ("Long Beach", "CA"): 455_000, ("Miami", "FL"): 450_000, ("Oakland", "CA"): 435_000,
    ("Minneapolis", "MN"): 430_000, ("Tulsa", "OK"): 410_000, ("Bakersfield", "CA"): 405_000,
    ("Wichita", "KS"): 400_000, ("Arlington", "TX"): 400_000, ("Tampa", "FL"): 385_000,
    ("New Orleans", "LA"): 365_000, ("Cleveland", "OH"): 365_000, ("Honolulu", "HI"): 345_000,
    ("Anaheim", "CA"): 345_000, ("Lexington", "KY"): 320_000, ("Stockton", "CA"): 320_000,
    ("Corpus Christi", "TX"): 315_000, ("Henderson", "NV"): 320_000, ("Riverside", "CA"): 315_000,
    ("Newark", "NJ"): 305_000, ("St. Paul", "MN"): 305_000, ("Santa Ana", "CA"): 310_000,
    ("Cincinnati", "OH"): 310_000, ("Irvine", "CA"): 310_000, ("Orlando", "FL"): 310_000,
    ("Pittsburgh", "PA"): 300_000, ("St. Louis", "MO"): 285_000, ("Greensboro", "NC"): 300_000,
    ("Jersey City", "NJ"): 290_000, ("Anchorage", "AK"): 290_000, ("Lincoln", "NE"): 290_000,
    ("Plano", "TX"): 290_000, ("Durham", "NC"): 285_000, ("Buffalo", "NY"): 275_000,
    ("Chandler", "AZ"): 275_000, ("Chula Vista", "CA"): 275_000, ("Toledo", "OH"): 265_000,
    ("Madison", "WI"): 270_000, ("Gilbert", "AZ"): 275_000, ("Reno", "NV"): 265_000,
    ("Fort Wayne", "IN"): 265_000, ("St. Petersburg", "FL"): 260_000, ("Lubbock", "TX"): 260_000,
    ("Irving", "TX"): 255_000, ("Laredo", "TX"): 255_000, ("Winston-Salem", "NC"): 250_000,
    ("Chesapeake", "VA"): 250_000, ("Glendale", "AZ"): 250_000, ("Garland", "TX"): 245_000,
    ("Scottsdale", "AZ"): 245_000, ("Boise", "ID"): 240_000, ("Norfolk", "VA"): 235_000,
    ("Spokane", "WA"): 230_000, ("Fremont", "CA"): 230_000, ("Richmond", "VA"): 225_000,
    ("Baton Rouge", "LA"): 225_000, ("Des Moines", "IA"): 215_000,
}
NATIONAL_POPULATION_FALLBACK = 300_000

CITIES_DATA = [
    ("New York", "NY", 65.0, 105.0, 2800.0, 0.0988, 5, 4),
    ("Los Angeles", "CA", 55.0, 90.0, 2300.0, 0.0600, 0, 3),
    ("Chicago", "IL", 50.0, 82.0, 2100.0, 0.0495, 8, 4),
    ("Houston", "TX", 38.0, 65.0, 1400.0, 0.0000, 0, 2),
    ("Phoenix", "AZ", 42.0, 70.0, 1500.0, 0.0250, 0, 2),
    ("Philadelphia", "PA", 48.0, 80.0, 2166.0, 0.0682, 6, 4),
    ("San Antonio", "TX", 36.0, 60.0, 1300.0, 0.0000, 0, 2),
    ("San Diego", "CA", 52.0, 85.0, 2100.0, 0.0600, 0, 3),
    ("Dallas", "TX", 42.0, 72.0, 1600.0, 0.0000, 0, 2),
    ("San Jose", "CA", 58.0, 95.0, 2400.0, 0.0600, 0, 3),
    ("Austin", "TX", 48.0, 80.0, 1850.0, 0.0000, 0, 3),
    ("Jacksonville", "FL", 38.0, 62.0, 1350.0, 0.0000, 0, 2),
    ("Fort Worth", "TX", 40.0, 68.0, 1450.0, 0.0000, 0, 2),
    ("Columbus", "OH", 42.0, 70.0, 1500.0, 0.0475, 5, 3),
    ("Charlotte", "NC", 44.0, 72.0, 1550.0, 0.0450, 2, 3),
    ("Indianapolis", "IN", 40.0, 65.0, 1400.0, 0.0495, 6, 2),
    ("San Francisco", "CA", 68.0, 110.0, 2900.0, 0.0600, 0, 3),
    ("Seattle", "WA", 58.0, 95.0, 2300.0, 0.0000, 3, 3),
    ("Denver", "CO", 48.0, 80.0, 1800.0, 0.0440, 6, 3),
    ("Oklahoma City", "OK", 35.0, 58.0, 1200.0, 0.0475, 3, 2),
    ("Nashville", "TN", 48.0, 80.0, 1800.0, 0.0000, 2, 3),
    ("El Paso", "TX", 32.0, 52.0, 1150.0, 0.0000, 0, 2),
    ("Washington", "DC", 58.0, 95.0, 2400.0, 0.0650, 4, 4),
    ("Las Vegas", "NV", 45.0, 75.0, 1650.0, 0.0000, 0, 3),
    ("Boston", "MA", 58.0, 95.0, 2400.0, 0.0900, 7, 4),
    ("Portland", "OR", 48.0, 80.0, 1850.0, 0.0875, 4, 3),
    ("Louisville", "KY", 38.0, 62.0, 1300.0, 0.0670, 4, 2),
    ("Memphis", "TN", 36.0, 58.0, 1200.0, 0.0000, 2, 2),
    ("Detroit", "MI", 40.0, 65.0, 1400.0, 0.0665, 8, 3),
    ("Baltimore", "MD", 45.0, 75.0, 1700.0, 0.0800, 5, 3),
    ("Milwaukee", "WI", 40.0, 65.0, 1400.0, 0.0530, 8, 2),
    ("Albuquerque", "NM", 36.0, 60.0, 1250.0, 0.0490, 2, 2),
    ("Tucson", "AZ", 36.0, 60.0, 1250.0, 0.0250, 0, 2),
    ("Fresno", "CA", 38.0, 62.0, 1350.0, 0.0500, 0, 2),
    ("Sacramento", "CA", 48.0, 80.0, 1800.0, 0.0600, 0, 3),
    ("Mesa", "AZ", 38.0, 65.0, 1350.0, 0.0250, 0, 2),
    ("Kansas City", "MO", 40.0, 68.0, 1400.0, 0.0595, 6, 2),
    ("Atlanta", "GA", 50.0, 82.0, 1900.0, 0.0549, 1, 3),
    ("Omaha", "NE", 38.0, 62.0, 1300.0, 0.0584, 7, 2),
    ("Colorado Springs", "CO", 42.0, 70.0, 1500.0, 0.0440, 6, 2),
    ("Raleigh", "NC", 45.0, 75.0, 1600.0, 0.0450, 2, 3),
    ("Virginia Beach", "VA", 40.0, 68.0, 1400.0, 0.0575, 2, 2),
    ("Long Beach", "CA", 50.0, 82.0, 1950.0, 0.0600, 0, 3),
    ("Miami", "FL", 55.0, 90.0, 2200.0, 0.0000, 0, 3),
    ("Oakland", "CA", 58.0, 95.0, 2300.0, 0.0600, 0, 3),
    ("Minneapolis", "MN", 48.0, 80.0, 1750.0, 0.0680, 9, 3),
    ("Tulsa", "OK", 35.0, 58.0, 1200.0, 0.0475, 3, 2),
    ("Bakersfield", "CA", 36.0, 60.0, 1300.0, 0.0500, 0, 2),
    ("Wichita", "KS", 34.0, 55.0, 1150.0, 0.0570, 6, 2),
    ("Arlington", "TX", 40.0, 68.0, 1450.0, 0.0000, 0, 2),
    ("Tampa", "FL", 45.0, 75.0, 1650.0, 0.0000, 0, 3),
    ("New Orleans", "LA", 42.0, 70.0, 1500.0, 0.0425, 0, 3),
    ("Cleveland", "OH", 38.0, 62.0, 1300.0, 0.0525, 8, 2),
    ("Honolulu", "HI", 55.0, 90.0, 2300.0, 0.0725, 0, 3),
    ("Anaheim", "CA", 52.0, 85.0, 2050.0, 0.0600, 0, 3),
    ("Lexington", "KY", 38.0, 62.0, 1300.0, 0.0675, 4, 2),
    ("Stockton", "CA", 40.0, 65.0, 1450.0, 0.0600, 0, 2),
    ("Corpus Christi", "TX", 36.0, 58.0, 1200.0, 0.0000, 0, 2),
    ("Henderson", "NV", 45.0, 75.0, 1600.0, 0.0000, 0, 2),
    ("Riverside", "CA", 44.0, 72.0, 1650.0, 0.0600, 0, 2),
    ("Newark", "NJ", 48.0, 80.0, 1900.0, 0.0637, 5, 3),
    ("St. Paul", "MN", 45.0, 75.0, 1600.0, 0.0680, 9, 2),
    ("Santa Ana", "CA", 50.0, 82.0, 1950.0, 0.0600, 0, 3),
    ("Cincinnati", "OH", 40.0, 68.0, 1400.0, 0.0455, 6, 2),
    ("Irvine", "CA", 55.0, 90.0, 2200.0, 0.0600, 0, 3),
    ("Orlando", "FL", 45.0, 75.0, 1650.0, 0.0000, 0, 3),
    ("Pittsburgh", "PA", 42.0, 70.0, 1500.0, 0.0607, 7, 2),
    ("St. Louis", "MO", 40.0, 65.0, 1350.0, 0.0595, 6, 2),
    ("Greensboro", "NC", 38.0, 62.0, 1300.0, 0.0450, 2, 2),
    ("Jersey City", "NJ", 55.0, 90.0, 2300.0, 0.0637, 5, 3),
    ("Anchorage", "AK", 48.0, 80.0, 1700.0, 0.0000, 12, 2),
    ("Lincoln", "NE", 36.0, 58.0, 1250.0, 0.0584, 7, 2),
    ("Plano", "TX", 45.0, 75.0, 1650.0, 0.0000, 0, 2),
    ("Durham", "NC", 44.0, 72.0, 1550.0, 0.0450, 2, 2),
    ("Buffalo", "NY", 38.0, 62.0, 1300.0, 0.0650, 12, 2),
    ("Chandler", "AZ", 42.0, 70.0, 1500.0, 0.0250, 0, 2),
    ("Chula Vista", "CA", 48.0, 80.0, 1850.0, 0.0600, 0, 3),
    ("Toledo", "OH", 34.0, 55.0, 1150.0, 0.0525, 7, 2),
    ("Madison", "WI", 44.0, 72.0, 1550.0, 0.0530, 8, 2),
    ("Gilbert", "AZ", 42.0, 70.0, 1500.0, 0.0250, 0, 2),
    ("Reno", "NV", 45.0, 75.0, 1600.0, 0.0000, 3, 2),
    ("Fort Wayne", "IN", 35.0, 58.0, 1200.0, 0.0450, 6, 2),
    ("St. Petersburg", "FL", 44.0, 72.0, 1600.0, 0.0000, 0, 2),
    ("Lubbock", "TX", 35.0, 58.0, 1200.0, 0.0000, 0, 2),
    ("Irving", "TX", 42.0, 70.0, 1500.0, 0.0000, 0, 2),
    ("Laredo", "TX", 32.0, 52.0, 1100.0, 0.0000, 0, 2),
    ("Winston-Salem", "NC", 38.0, 62.0, 1300.0, 0.0450, 2, 2),
    ("Chesapeake", "VA", 40.0, 65.0, 1350.0, 0.0575, 2, 2),
    ("Glendale", "AZ", 40.0, 65.0, 1400.0, 0.0250, 0, 2),
    ("Garland", "TX", 38.0, 62.0, 1350.0, 0.0000, 0, 2),
    ("Scottsdale", "AZ", 48.0, 80.0, 1800.0, 0.0250, 0, 3),
    ("Boise", "ID", 42.0, 70.0, 1500.0, 0.0580, 4, 2),
    ("Norfolk", "VA", 40.0, 65.0, 1350.0, 0.0575, 2, 2),
    ("Spokane", "WA", 40.0, 65.0, 1400.0, 0.0000, 6, 2),
    ("Fremont", "CA", 58.0, 95.0, 2400.0, 0.0600, 0, 3),
    ("Richmond", "VA", 42.0, 70.0, 1450.0, 0.0575, 2, 2),
    ("Baton Rouge", "LA", 38.0, 62.0, 1300.0, 0.0425, 0, 2),
    ("Des Moines", "IA", 38.0, 62.0, 1300.0, 0.0570, 7, 2),
]

def run_city_simulation(city: str, state: str, base_price: float, combo_price: float, lease: float, tax_rate: float, snow_days: int, walkin_avg: int) -> dict:
    np.random.seed(42)
    open_days_per_year = 245
    total_weekdays = 260
    
    annual_lease = (lease + 200.0) * 12.0
    daily_overhead = annual_lease / float(total_weekdays)
    
    # Mandatory 30-min lunch/reset break isn't bookable chair time -> 450 usable minutes.
    max_daily_mins = 480 - 30
    min_std = 40
    min_combo = 60

    cc_rate = 0.030
    cogs_std = 1.80
    cogs_combo = 3.20
    se_tax_rate = 0.153
    health_insurance_annual = 6000.0
    filing_status = "head_of_household"
    
    current_clients = 180
    days_worked = 0
    
    total_rev = 0.0
    total_cc = 0.0
    total_cogs = 0.0
    total_cuts = 0
    total_bundles = 0
    total_mins = 0
    
    for day in range(1, 366):
        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][(day - 1) % 7]
        if dow in ["Mon", "Sun"]: continue
            
        is_winter = snow_days > 0 and (day <= 60 or day >= 335)
        is_snow_closure = is_winter and (np.random.random() < (snow_days / 35.0))
        
        if is_snow_closure or days_worked >= open_days_per_year or (np.random.random() < (15.0 / 260.0)):
            continue
            
        days_worked += 1
        
        weather_mod = 1.0
        if is_winter and not is_snow_closure and (np.random.random() < 0.40):
            weather_mod = 0.35
            
        is_peak = dow in ["Fri", "Sat"]
        bundle_rate = 0.35 * (1.40 if is_peak else 1.0)
        
        base_demand = (current_clients / 28.0) * weather_mod
        walkins = int(np.random.poisson(walkin_avg if is_peak else max(1, walkin_avg - 1)) * weather_mod)
        tot_demand = int(round(base_demand + walkins))
        
        day_std = 0
        day_combo = 0
        day_mins = 0
        
        des_combo = int(round(tot_demand * bundle_rate))
        des_std = max(0, tot_demand - des_combo)
        
        if is_peak:
            while des_combo > 0 and (day_mins + min_combo) <= max_daily_mins:
                day_combo += 1; day_mins += min_combo; des_combo -= 1
            while des_std > 0 and (day_mins + min_std) <= max_daily_mins:
                day_std += 1; day_mins += min_std; des_std -= 1
        else:
            while des_std > 0 and (day_mins + min_std) <= max_daily_mins:
                day_std += 1; day_mins += min_std; des_std -= 1
            while des_combo > 0 and (day_mins + min_combo) <= max_daily_mins:
                day_combo += 1; day_mins += min_combo; des_combo -= 1
                
        day_rev = (day_std * base_price) + (day_combo * combo_price)
        day_cc = day_rev * cc_rate
        day_c = (day_std * cogs_std) + (day_combo * cogs_combo)
        
        total_rev += day_rev
        total_cc += day_cc
        total_cogs += day_c
        total_cuts += (day_std + day_combo)
        total_bundles += day_combo
        total_mins += day_mins
        
    pretax_profit = total_rev - total_cc - total_cogs - annual_lease
    se_tax = max(0.0, (pretax_profit * 0.9235) * se_tax_rate)
    state_city_tax = max(0.0, pretax_profit * tax_rate)
    fed_tax = federal_income_tax(pretax_profit, se_tax, health_insurance_annual, filing_status)
    true_take_home = pretax_profit - se_tax - state_city_tax - fed_tax - health_insurance_annual

    utilization = (total_mins / (days_worked * max_daily_mins)) * 100.0 if days_worked > 0 else 0.0
    aov = total_rev / max(1, total_cuts)

    population = CITY_POPULATIONS.get((city, state), NATIONAL_POPULATION_FALLBACK)
    feasibility = assess_market_feasibility(population, state, total_cuts)

    return {
        "city": f"{city}, {state}",
        "state": state,
        "days_worked": days_worked,
        "gross_rev": total_rev,
        "lease_annual": annual_lease,
        "pretax_profit": pretax_profit,
        "se_tax": se_tax,
        "state_city_tax": state_city_tax,
        "federal_tax": fed_tax,
        "health_insurance": health_insurance_annual,
        "total_tax": se_tax + state_city_tax + fed_tax,
        "take_home": true_take_home,
        "aov": aov,
        "utilization": utilization,
        "total_cuts": total_cuts,
        "total_bundles": total_bundles,
        "population_est": population,
        "existing_shops_est": round(feasibility["existing_shops_est"]),
        "saturation_pct_low": feasibility["saturation_pct_range"][0],
        "saturation_pct_high": feasibility["saturation_pct_range"][1],
        "wills_share_pct_low": feasibility["wills_market_share_pct_range"][0],
        "wills_share_pct_high": feasibility["wills_market_share_pct_range"][1],
        "feasibility": feasibility["feasibility"],
    }

def main():
    results = [run_city_simulation(*data) for data in CITIES_DATA]
    df = pd.DataFrame(results).sort_values(by="take_home", ascending=False).reset_index(drop=True)
    df.to_csv("/root/research/barbershop_twin/results/top_100_cities_results.csv", index=True)
    print("CSV Saved!")

if __name__ == "__main__":
    main()

"""
run_twin.py
CLI execution tool for Fresh & Focused Barbershop Digital Twin (Will: Solo 1-Chair Model).
Runs 365-day simulations across all benchmark scenarios, outputs ASCII KPI tables,
and generates high-resolution Matplotlib comparison charts.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from simulation import BarbershopDigitalTwin
from scenarios import get_baseline_strategy, get_static_marketing_strategy, get_autonomous_ai_strategy

def run_all_scenarios():
    print("=" * 78)
    print(" ✂️  FRESH & FOCUSED BARBERSHOP DIGITAL TWIN (HOUSTON HEIGHTS 77008)")
    print("     SOLO OPERATOR MODEL: WILL (1 CHAIR, SUITE 236) - WORK-LIFE OPTIMIZED")
    print("=" * 78)

    scenarios = [
        get_baseline_strategy(),
        get_static_marketing_strategy(),
        get_autonomous_ai_strategy()
    ]

    results = {}

    for strat in scenarios:
        print(f"\nrunning Simulation: [{strat['name']}] over 365 days...")
        # Set random seed for fair comparison across scenarios
        np.random.seed(42)
        twin = BarbershopDigitalTwin(initial_customers=180)
        res = twin.run_simulation(days=365, strategy=strat)
        results[strat["name"]] = res
        
        s = res["summary"]
        print("-" * 58)
        print(f"  Gross Service Revenue:   ${s['total_revenue']:,.2f}")
        print(f"  Fixed Suite Overhead:    ${s['total_fixed_overhead']:,.2f} ($1,400 rent + $200 software/insurance)")
        print(f"  Marketing / Ad Spend:    ${s['total_ad_spend']:,.2f}")
        print(f"  ⭐ WILL'S NET TAKE-HOME:  ${s['total_net_profit']:,.2f} (For Will & Daughter)")
        print(f"  Avg Chair Utilization:   {s['avg_utilization_pct']:.1f}%")
        print(f"  Average Order Value:     ${s['aov']:.2f}")
        print(f"  Customer Churn:          {s['total_churned']} regulars lost")
        print("-" * 58)

    # Print Comparative ASCII Summary Table
    print("\n" + "=" * 80)
    print(" 📊 ANNUAL COMPARATIVE FINANCIAL & OPERATIONAL PERFORMANCE (WILL'S SUITE 236)")
    print("=" * 80)
    print(f"{'Metric':<26} | {'Scenario 1 (Baseline)':<22} | {'Scenario 2 (Static)':<22} | {'Scenario 3 (Autonomous AI)':<22}")
    print("-" * 102)
    
    names = [s["name"] for s in scenarios]
    s1, s2, s3 = results[names[0]]["summary"], results[names[1]]["summary"], results[names[2]]["summary"]
    
    print(f"{'Gross Service Revenue':<26} | ${s1['total_revenue']:<21,.2f} | ${s2['total_revenue']:<21,.2f} | ${s3['total_revenue']:<21,.2f}")
    print(f"{'Fixed Overhead':<26} | ${s1['total_fixed_overhead']:<21,.2f} | ${s2['total_fixed_overhead']:<21,.2f} | ${s3['total_fixed_overhead']:<21,.2f}")
    print(f"{'Ad Spend / Marketing':<26} | ${s1['total_ad_spend']:<21,.2f} | ${s2['total_ad_spend']:<21,.2f} | ${s3['total_ad_spend']:<21,.2f}")
    print("-" * 102)
    print(f"{'⭐ WILLS NET TAKE-HOME':<26} | ${s1['total_net_profit']:<21,.2f} | ${s2['total_net_profit']:<21,.2f} | ${s3['total_net_profit']:<21,.2f}")
    print("-" * 102)
    print(f"{'Chair Utilization':<26} | {s1['avg_utilization_pct']:<21.1f}% | {s2['avg_utilization_pct']:<21.1f}% | {s3['avg_utilization_pct']:<21.1f}%")
    print(f"{'Average Order Value':<26} | ${s1['aov']:<21.2f} | ${s2['aov']:<21.2f} | ${s3['aov']:<21.2f}")
    print(f"{'Regulars Churned':<26} | {s1['total_churned']:<21} | {s2['total_churned']:<21} | {s3['total_churned']:<21}")
    print(f"{'Ending Active Clients':<26} | {s1['final_active_regulars']:<21} | {s2['final_active_regulars']:<21} | {s3['final_active_regulars']:<21}")
    print("=" * 102)

    # Save Plots
    os.makedirs("/root/research/barbershop_twin/results", exist_ok=True)
    plot_results(results, names)
    print("\n✅ Simulation charts successfully generated in /root/research/barbershop_twin/results/")

def plot_results(results, names):
    df1 = results[names[0]]["daily_df"]
    df2 = results[names[1]]["daily_df"]
    df3 = results[names[2]]["daily_df"]

    # Plot 1: Cumulative Net Take-Home Profit
    plt.figure(figsize=(12, 6))
    plt.plot(df1["day"], df1["net_profit"].cumsum(), label="Scenario 1: Baseline Manual", color="#ef4444", linewidth=2)
    plt.plot(df2["day"], df2["net_profit"].cumsum(), label="Scenario 2: Static Marketing", color="#f97316", linewidth=2, linestyle="--")
    plt.plot(df3["day"], df3["net_profit"].cumsum(), label="Scenario 3: Autonomous AI Loop", color="#10b981", linewidth=3)
    plt.title("Will's Cumulative Take-Home Profit ($) - Supporting Daughter & Suite 236", fontsize=14, fontweight="bold")
    plt.xlabel("Day of Year", fontsize=12)
    plt.ylabel("Cumulative Take-Home Profit ($)", fontsize=12)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig("/root/research/barbershop_twin/results/cumulative_profit.png", dpi=300)
    plt.close()

    # Plot 2: Chair Utilization Over Time (30-day moving average)
    plt.figure(figsize=(12, 6))
    plt.plot(df1["day"], df1["utilization_pct"].rolling(30).mean(), label="Baseline Utilization", color="#ef4444", alpha=0.8)
    plt.plot(df3["day"], df3["utilization_pct"].rolling(30).mean(), label="Autonomous AI Utilization", color="#3b82f6", linewidth=2.5)
    plt.title("Will's 1-Chair Utilization Curve (30-Day Moving Average %)", fontsize=14, fontweight="bold")
    plt.xlabel("Day of Year", fontsize=12)
    plt.ylabel("Chair Utilization %", fontsize=12)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig("/root/research/barbershop_twin/results/chair_utilization.png", dpi=300)
    plt.close()

if __name__ == "__main__":
    run_all_scenarios()

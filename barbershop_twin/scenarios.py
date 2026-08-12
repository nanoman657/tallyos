"""
scenarios.py
Benchmark scenario configurations for Fresh & Focused Barbershop Digital Twin.
Compares Baseline vs Static Rule-Based vs Autonomous AI Control Loop.
"""

from typing import Dict, Any

def get_baseline_strategy() -> Dict[str, Any]:
    """
    Scenario 1: Baseline Manual Operations.
    No automated SMS reminders, no mid-week off-peak discounts, no bundle upselling, no geo-targeted ads.
    """
    return {
        "name": "Scenario 1: Baseline (Manual Operations)",
        "enable_sms_day28": False,
        "enable_midweek_discount": False,
        "enable_bundle_upsell": False,
        "enable_heb_geo_ads": False,
        "autonomous_ai_loop": False,
        "daily_ad_budget": 0.0
    }

def get_static_marketing_strategy() -> Dict[str, Any]:
    """
    Scenario 2: Static Rule-Based Marketing.
    Always-on SMS reminders at Day 28, constant H-E-B geo-targeted ad spend ($15/day), continuous checkout bundle upselling.
    """
    return {
        "name": "Scenario 2: Static Rule-Based Marketing",
        "enable_sms_day28": True,
        "enable_midweek_discount": True,
        "enable_bundle_upsell": True,
        "enable_heb_geo_ads": True,
        "autonomous_ai_loop": False,
        "daily_ad_budget": 15.0
    }

def get_autonomous_ai_strategy() -> Dict[str, Any]:
    """
    Scenario 3: Autonomous AI Digital Twin Loop (The Future State).
    The AI senses real-time Booksy calendar vacancy and Houston weather forecasts.
    Dynamically triggers SMS blasts, WFH off-peak discounts, and H-E-B geo-ads ONLY when required to maximize ROI.
    """
    return {
        "name": "Scenario 3: Autonomous AI Control Loop",
        "enable_sms_day28": False,  # Dynamically toggled by AI
        "enable_midweek_discount": False, # Dynamically toggled by AI
        "enable_bundle_upsell": True, # Always attempt bundle upselling
        "enable_heb_geo_ads": False, # Dynamically toggled by AI during rain/slumps
        "autonomous_ai_loop": True,
        "daily_ad_budget": 20.0
    }

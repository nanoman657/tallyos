"""
Runtime configuration from environment variables, so the same code runs as a
local demo (simulated Google Ads) or against a real Google Ads account.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


@dataclass
class GrowthConfig:
    """Guardrails and unit economics for the sense-think-act loop."""
    forecast_horizon_days: int = 14
    target_utilization: float = 0.85         # fill chairs to 85%; leave slack for walk-ins and overruns
    max_total_daily_budget: float = 40.0     # hard ceiling across ALL loop-managed campaigns ($/day)
    min_campaign_daily_budget: float = 5.0
    budget_step_up: float = 1.25             # max multiplicative budget raise per cycle
    budget_step_down: float = 0.70           # multiplicative cut when the book is already full
    ltv_months: float = 12.0                 # horizon for client lifetime value
    max_cpa_fraction_of_ltv: float = 0.33    # never pay more than 1/3 of a client's 12-month margin
    signup_to_booking_rate: float = 0.60     # prior share of ad sign-ups that book a first cut
    min_clicks_for_judgement: int = 30       # don't pause a campaign on noise
    # Beta prior on click -> sign-up conversion (mean 5%, worth ~40 clicks of evidence)
    cvr_prior_alpha: float = 2.0
    cvr_prior_beta: float = 38.0
    default_cpc: float = 2.50                # prior cost per click for local "barber near me" search
    lookback_days: int = 28                  # window for ad performance + attribution in SENSE


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgresql://tallyos:tallyos@localhost:5432/tallyos"))
    # "simulated" (default, offline demo) or "google" (real Google Ads API)
    ads_backend: str = field(default_factory=lambda: os.environ.get("TALLYOS_ADS_BACKEND", "simulated"))
    # Real-money safety: campaigns the loop creates on a live account start PAUSED
    # unless this is explicitly turned on.
    ads_auto_enable: bool = field(default_factory=lambda: _env_bool("TALLYOS_ADS_AUTO_ENABLE", False))
    google_ads_customer_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", ""))
    google_ads_conversion_action: str = field(default_factory=lambda: os.environ.get("GOOGLE_ADS_CONVERSION_ACTION", ""))
    google_ads_config_path: str = field(default_factory=lambda: os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH", ""))
    shop_latitude: float = field(default_factory=lambda: _env_float("TALLYOS_SHOP_LAT", 29.8105))
    shop_longitude: float = field(default_factory=lambda: _env_float("TALLYOS_SHOP_LNG", -95.3980))
    ad_radius_miles: float = field(default_factory=lambda: _env_float("TALLYOS_AD_RADIUS_MILES", 3.0))
    booking_url: str = field(default_factory=lambda: os.environ.get("TALLYOS_BOOKING_URL", "http://localhost:8000/join.html"))
    frontend_dir: str = field(default_factory=lambda: os.environ.get(
        "TALLYOS_FRONTEND_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend")))
    growth: GrowthConfig = field(default_factory=GrowthConfig)


@lru_cache
def get_settings() -> Settings:
    return Settings()

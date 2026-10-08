"""
Ad-platform interface used by the growth loop.

SENSE pulls daily metrics and click ids (gclids) through it, ACT creates /
re-budgets / pauses campaigns through it, and uploads offline conversions so
Google's bidding learns which clicks turned into real sign-ups.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Protocol


@dataclass
class CampaignSpec:
    name: str
    daily_budget: float
    target_weekdays: List[int]          # Monday = 0; becomes the campaign ad schedule
    headlines: List[str]                # responsive search ad, <= 30 chars each
    descriptions: List[str]             # <= 90 chars each
    keywords: List[str]
    final_url: str
    latitude: float
    longitude: float
    radius_miles: float
    enabled: bool = False


@dataclass
class DailyMetric:
    external_id: str
    date: date
    impressions: int
    clicks: int
    cost: float
    conversions: float = 0.0


@dataclass
class Click:
    gclid: str
    external_id: str
    date: date


@dataclass
class OfflineConversion:
    gclid: str
    at: datetime
    value: float = 0.0
    currency: str = "USD"


@dataclass
class UploadResult:
    uploaded: int
    failed: List[str] = field(default_factory=list)


class AdsPlatform(Protocol):
    name: str

    def create_campaign(self, spec: CampaignSpec) -> str:
        """Create campaign + budget + ad group + ad + keywords + geo; return external id."""

    def update_budget(self, external_id: str, daily_budget: float) -> None: ...

    def update_schedule(self, external_id: str, weekdays: List[int]) -> None: ...

    def set_status(self, external_id: str, status: str) -> None:
        """status: ENABLED | PAUSED"""

    def fetch_daily_metrics(self, start: date, end: date) -> List[DailyMetric]: ...

    def fetch_clicks(self, start: date, end: date) -> List[Click]: ...

    def upload_conversions(self, conversions: List[OfflineConversion]) -> UploadResult: ...

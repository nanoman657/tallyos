"""
Live Google Ads adapter (official `google-ads` Python client).

Enable with:
    TALLYOS_ADS_BACKEND=google
    GOOGLE_ADS_CONFIGURATION_FILE_PATH=/path/to/google-ads.yaml   (or GOOGLE_ADS_* env vars)
    GOOGLE_ADS_CUSTOMER_ID=1234567890
    GOOGLE_ADS_CONVERSION_ACTION=987654321   # an "Import > Other data sources / clicks" conversion action

Campaigns are Search campaigns with a proximity radius around the shop, an ad
schedule on the gap weekdays, phrase-match local keywords and one responsive
search ad, bid with Maximize Clicks (TargetSpend) under a CPC ceiling. Once
enough offline conversions have been uploaded the owner can switch bidding to
Maximize Conversions in Google Ads; the loop only manages budget, schedule
and status, so it won't fight that change.
"""

import uuid
from datetime import date, timedelta
from typing import List

from ..config import Settings
from .base import CampaignSpec, Click, DailyMetric, OfflineConversion, UploadResult

CPC_CEILING_MICROS = 6_000_000
WEEKDAY_ENUM = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


class GoogleAdsPlatform:
    name = "google"

    def __init__(self, settings: Settings):
        try:
            from google.ads.googleads.client import GoogleAdsClient
            from google.api_core import protobuf_helpers
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("TALLYOS_ADS_BACKEND=google requires `pip install google-ads`") from exc
        if not settings.google_ads_customer_id:
            raise RuntimeError("GOOGLE_ADS_CUSTOMER_ID is not set")
        self.client = (GoogleAdsClient.load_from_storage(settings.google_ads_config_path)
                       if settings.google_ads_config_path else GoogleAdsClient.load_from_env())
        self.customer_id = settings.google_ads_customer_id
        action = settings.google_ads_conversion_action
        self.conversion_action = (action if action.startswith("customers/")
                                  else f"customers/{self.customer_id}/conversionActions/{action}" if action else "")
        self._field_mask = protobuf_helpers.field_mask

    # ---------------------------------------------------------------- helpers
    def _enum(self, enum_name: str, value: str):
        return getattr(getattr(self.client.enums, enum_name), value)

    def _search(self, query: str):
        ga = self.client.get_service("GoogleAdsService")
        for batch in ga.search_stream(customer_id=self.customer_id, query=query):
            yield from batch.results

    def _schedule_ops(self, campaign_rn: str, weekdays: List[int]) -> list:
        ops = []
        for wd in sorted(weekdays) or range(7):
            op = self.client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_rn
            crit.ad_schedule.day_of_week = self._enum("DayOfWeekEnum", WEEKDAY_ENUM[wd])
            crit.ad_schedule.start_hour = 0
            crit.ad_schedule.end_hour = 24
            crit.ad_schedule.start_minute = self._enum("MinuteOfHourEnum", "ZERO")
            crit.ad_schedule.end_minute = self._enum("MinuteOfHourEnum", "ZERO")
            ops.append(op)
        return ops

    # ---------------------------------------------------------------- campaign management
    def create_campaign(self, spec: CampaignSpec) -> str:
        c = self.client
        budget_op = c.get_type("CampaignBudgetOperation")
        budget = budget_op.create
        budget.name = f"{spec.name} budget {uuid.uuid4().hex[:6]}"
        budget.delivery_method = self._enum("BudgetDeliveryMethodEnum", "STANDARD")
        budget.amount_micros = int(round(spec.daily_budget * 1_000_000))
        budget.explicitly_shared = False
        budget_rn = c.get_service("CampaignBudgetService").mutate_campaign_budgets(
            customer_id=self.customer_id, operations=[budget_op]).results[0].resource_name

        camp_op = c.get_type("CampaignOperation")
        camp = camp_op.create
        camp.name = spec.name
        camp.advertising_channel_type = self._enum("AdvertisingChannelTypeEnum", "SEARCH")
        camp.status = self._enum("CampaignStatusEnum", "ENABLED" if spec.enabled else "PAUSED")
        camp.campaign_budget = budget_rn
        camp.target_spend.cpc_bid_ceiling_micros = CPC_CEILING_MICROS
        camp.network_settings.target_google_search = True
        camp.network_settings.target_search_network = False
        camp.network_settings.target_content_network = False
        if hasattr(camp, "contains_eu_political_advertising"):
            camp.contains_eu_political_advertising = self._enum(
                "EuPoliticalAdvertisingStatusEnum", "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING")
        campaign_rn = c.get_service("CampaignService").mutate_campaigns(
            customer_id=self.customer_id, operations=[camp_op]).results[0].resource_name

        geo_op = c.get_type("CampaignCriterionOperation")
        geo = geo_op.create
        geo.campaign = campaign_rn
        geo.proximity.geo_point.latitude_in_micro_degrees = int(spec.latitude * 1_000_000)
        geo.proximity.geo_point.longitude_in_micro_degrees = int(spec.longitude * 1_000_000)
        geo.proximity.radius = spec.radius_miles
        geo.proximity.radius_units = self._enum("ProximityRadiusUnitsEnum", "MILES")
        c.get_service("CampaignCriterionService").mutate_campaign_criteria(
            customer_id=self.customer_id, operations=[geo_op, *self._schedule_ops(campaign_rn, spec.target_weekdays)])

        group_op = c.get_type("AdGroupOperation")
        group = group_op.create
        group.name = f"{spec.name} - local search"
        group.campaign = campaign_rn
        group.status = self._enum("AdGroupStatusEnum", "ENABLED")
        group.type_ = self._enum("AdGroupTypeEnum", "SEARCH_STANDARD")
        group_rn = c.get_service("AdGroupService").mutate_ad_groups(
            customer_id=self.customer_id, operations=[group_op]).results[0].resource_name

        kw_ops = []
        for text in spec.keywords:
            op = c.get_type("AdGroupCriterionOperation")
            crit = op.create
            crit.ad_group = group_rn
            crit.status = self._enum("AdGroupCriterionStatusEnum", "ENABLED")
            crit.keyword.text = text
            crit.keyword.match_type = self._enum("KeywordMatchTypeEnum", "PHRASE")
            kw_ops.append(op)
        c.get_service("AdGroupCriterionService").mutate_ad_group_criteria(
            customer_id=self.customer_id, operations=kw_ops)

        ad_op = c.get_type("AdGroupAdOperation")
        group_ad = ad_op.create
        group_ad.ad_group = group_rn
        group_ad.status = self._enum("AdGroupAdStatusEnum", "ENABLED")
        group_ad.ad.final_urls.append(spec.final_url)
        for text in spec.headlines:
            asset = c.get_type("AdTextAsset")
            asset.text = text
            group_ad.ad.responsive_search_ad.headlines.append(asset)
        for text in spec.descriptions:
            asset = c.get_type("AdTextAsset")
            asset.text = text
            group_ad.ad.responsive_search_ad.descriptions.append(asset)
        c.get_service("AdGroupAdService").mutate_ad_group_ads(customer_id=self.customer_id, operations=[ad_op])
        return campaign_rn

    def update_budget(self, external_id: str, daily_budget: float) -> None:
        row = next(iter(self._search(
            f"SELECT campaign.campaign_budget FROM campaign WHERE campaign.resource_name = '{external_id}'")))
        op = self.client.get_type("CampaignBudgetOperation")
        budget = op.update
        budget.resource_name = row.campaign.campaign_budget
        budget.amount_micros = int(round(daily_budget * 1_000_000))
        self.client.copy_from(op.update_mask, self._field_mask(None, budget._pb))
        self.client.get_service("CampaignBudgetService").mutate_campaign_budgets(
            customer_id=self.customer_id, operations=[op])

    def update_schedule(self, external_id: str, weekdays: List[int]) -> None:
        existing = [r.campaign_criterion.resource_name for r in self._search(
            "SELECT campaign_criterion.resource_name FROM campaign_criterion "
            f"WHERE campaign.resource_name = '{external_id}' AND campaign_criterion.type = 'AD_SCHEDULE'")]
        ops = []
        for rn in existing:
            op = self.client.get_type("CampaignCriterionOperation")
            op.remove = rn
            ops.append(op)
        ops += self._schedule_ops(external_id, weekdays)
        self.client.get_service("CampaignCriterionService").mutate_campaign_criteria(
            customer_id=self.customer_id, operations=ops)

    def set_status(self, external_id: str, status: str) -> None:
        op = self.client.get_type("CampaignOperation")
        camp = op.update
        camp.resource_name = external_id
        camp.status = self._enum("CampaignStatusEnum", status)
        self.client.copy_from(op.update_mask, self._field_mask(None, camp._pb))
        self.client.get_service("CampaignService").mutate_campaigns(customer_id=self.customer_id, operations=[op])

    # ---------------------------------------------------------------- reporting
    def fetch_daily_metrics(self, start: date, end: date) -> List[DailyMetric]:
        rows = self._search(
            "SELECT campaign.resource_name, segments.date, metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions FROM campaign "
            f"WHERE segments.date BETWEEN '{start:%Y-%m-%d}' AND '{end:%Y-%m-%d}' AND campaign.status != 'REMOVED'")
        return [DailyMetric(r.campaign.resource_name, date.fromisoformat(r.segments.date), r.metrics.impressions,
                            r.metrics.clicks, r.metrics.cost_micros / 1_000_000, r.metrics.conversions) for r in rows]

    def fetch_clicks(self, start: date, end: date) -> List[Click]:
        # click_view only accepts a single-day date filter (and keeps 90 days).
        start = max(start, date.today() - timedelta(days=89))
        clicks, day = [], start
        while day <= end:
            for r in self._search("SELECT click_view.gclid, campaign.resource_name FROM click_view "
                                  f"WHERE segments.date = '{day:%Y-%m-%d}'"):
                clicks.append(Click(r.click_view.gclid, r.campaign.resource_name, day))
            day += timedelta(days=1)
        return clicks

    def upload_conversions(self, conversions: List[OfflineConversion]) -> UploadResult:
        if not self.conversion_action:
            return UploadResult(uploaded=0, failed=[c.gclid for c in conversions])
        request = self.client.get_type("UploadClickConversionsRequest")
        request.customer_id = self.customer_id
        request.partial_failure = True
        for conv in conversions:
            cc = self.client.get_type("ClickConversion")
            cc.conversion_action = self.conversion_action
            cc.gclid = conv.gclid
            cc.conversion_value = float(conv.value)
            cc.currency_code = conv.currency
            stamp = conv.at.astimezone()   # shop-local naive time -> aware
            offset = stamp.strftime("%z")
            cc.conversion_date_time = stamp.strftime("%Y-%m-%d %H:%M:%S") + f"{offset[:3]}:{offset[3:]}"
            request.conversions.append(cc)
        response = self.client.get_service("ConversionUploadService").upload_click_conversions(request=request)
        # With partial_failure, failed rows come back as empty results at the same index.
        failed = [conv.gclid for conv, res in zip(conversions, response.results) if not res.gclid]
        return UploadResult(uploaded=len(conversions) - len(failed), failed=failed)


"""
simulation.py
Stochastic Simulation Engine for Solo Barber Will (1 Chair) Digital Twin.
Updated with True Peak Displacement Yield Management and Spendable Cash Accounting.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
from models import (
    CustomerAgent, ShopCapacity, HoustonEnvironment, ad_walkin_multiplier,
    AD_SALIENCE_DAILY_DECAY, AD_SALIENCE_BUILD_RATE_MAX, AD_SALIENCE_MAX_REACTIVATION_PROB,
)
from taxes import federal_income_tax

# Autonomous AI Loop dynamic thresholds -- reasoned assumptions, not sourced figures.
AI_CAPACITY_THROTTLE_UTILIZATION_PCT = 90.0   # trailing-window utilization above which volume ads pause
AI_CAPACITY_THROTTLE_WINDOW_DAYS = 7          # trailing window (open days) for the utilization throttle
AI_RECRUITMENT_ACTIVE_COUNT_THRESHOLD = 150   # active regulars below this forces recruitment-mode ads
AI_SALIENCE_MAINTENANCE_FLOOR = 0.30          # below this salience level, top up regardless of capacity/weekday
AI_SALIENCE_MAINTENANCE_SPEND_FRACTION = 0.35 # maintenance spend, as a fraction of the strategy's full daily_ad_budget

class BarbershopDigitalTwin:
    def __init__(self, initial_customers: int = 180, capacity: ShopCapacity = None):
        self.capacity = capacity if capacity else ShopCapacity()
        # Mandatory lunch/bathroom/reset break eats into the 480-min day before
        # slots are counted, so the chair isn't modeled as 100% back-to-back.
        usable_minutes = 480.0 - self.capacity.lunch_break_minutes
        self.capacity.max_daily_slots = int(usable_minutes // 40)
        self.customers: List[CustomerAgent] = []
        self._initialize_customers(initial_customers)
        self.days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        # Shop-level "mental availability" (0=none, 1=saturated) -- see AD_SALIENCE_*
        # constants in models.py. Builds with continuous local ad presence, decays
        # when ads go dark, and makes existing/lapsed clients modestly stickier.
        self.ad_salience = 0.0

    def _initialize_customers(self, count: int):
        for i in range(count):
            days_ago = int(np.random.uniform(1, 35))
            preferred = ["Friday", "Saturday"] if np.random.random() < 0.65 else ["Tuesday", "Wednesday", "Thursday"]
            agent = CustomerAgent(
                client_id=i,
                is_regular=True,
                days_since_last_cut=days_ago,
                preferred_days=preferred,
                price_sensitivity=np.random.beta(2, 5),
                bundle_receptivity=np.random.beta(3, 5)
            )
            self.customers.append(agent)

    def run_simulation(self, days: int = 365, strategy: Dict[str, Any] = None, start_day_of_year: int = 1) -> Dict[str, Any]:
        """
        Runs the daily discrete step simulation over the specified time horizon.
        Employs True Spendable Cash Accounting and Peak Displacement Yield Management.
        """
        if strategy is None:
            strategy = {
                "enable_sms_day28": False,
                "enable_midweek_discount": False,
                "enable_bundle_upsell": False,
                "enable_heb_geo_ads": False,
                "autonomous_ai_loop": False,
                "daily_ad_budget": 15.0
            }

        daily_records = []
        next_client_id = len(self.customers)
        total_ad_spend = 0.0
        total_gross_revenue = 0.0
        total_cc_fees = 0.0
        total_cogs = 0.0
        total_se_tax = 0.0
        total_state_city_tax = 0.0
        total_pretax_profit = 0.0
        total_true_take_home = 0.0
        total_churned = 0

        # Realistic Solo Schedule: Will takes 15 days off per year for sick leave, vacation, and child emergencies (245 open days/yr)
        open_days_per_year = 245
        daily_fixed_overhead = (self.capacity.fixed_monthly_lease + self.capacity.monthly_utilities_software) * 12.0 / open_days_per_year
        days_worked_so_far = 0

        total_reactivated = 0

        # State the Autonomous AI Loop reacts to -- carried from the last OPEN day
        # (not reset by closed Sun/Mon days, since "yesterday's numbers" from Will's
        # perspective means the last day he actually worked).
        prev_day_turnaways = 0
        recent_utilizations: List[float] = []

        for day in range(1, days + 1):
            day_of_week = self.days_of_week[(day - 1) % 7]
            # Mental availability decays every day, whether the shop is open or not --
            # continuous presence matters more than raw exposure count (Ephron/Ehrenberg-Bass).
            self.ad_salience *= AD_SALIENCE_DAILY_DECAY
            # Carryover ("adstock") entering today, BEFORE today's own spend is added --
            # today's walk-ins respond to accumulated prior-day awareness, not to money
            # being spent this same instant. A passive local-radius awareness ad (what
            # "geo-ads" models here) isn't a search-intent ad someone acts on immediately;
            # it works through carryover like any other MMM adstock effect.
            carryover_salience = self.ad_salience

            # Will takes Sundays and Mondays off for rest & daughter (5-day work week)
            if day_of_week in ["Monday", "Sunday"]:
                for c in self.customers:
                    if c.status == "ACTIVE": c.days_since_last_cut += 1
                daily_records.append({
                    "day": day, "day_of_week": day_of_week, "is_open": False, "revenue": 0.0,
                    "net_profit": 0.0, "utilization_pct": 0.0, "actual_cuts": 0, "bundle_upgrades": 0, "turnaways": 0,
                    "ad_salience": self.ad_salience
                })
                continue

            # Check for PTO / Sick / Child Emergency Day (randomly distributed up to 15 days/year)
            if days_worked_so_far >= open_days_per_year or (np.random.random() < (15.0 / 260.0)):
                for c in self.customers:
                    if c.status == "ACTIVE": c.days_since_last_cut += 1
                daily_records.append({
                    "day": day, "day_of_week": day_of_week, "is_open": False, "revenue": 0.0,
                    "net_profit": -daily_fixed_overhead, "utilization_pct": 0.0, "actual_cuts": 0, "bundle_upgrades": 0, "turnaways": 0,
                    "ad_salience": self.ad_salience
                })
                continue

            days_worked_so_far += 1

            # 1. Sense: Houston Weather & Environment
            calendar_day_of_year = ((start_day_of_year - 1 + day - 1) % 365) + 1
            weather = HoustonEnvironment.get_weather_modifier(calendar_day_of_year, is_philly_winter=False)
            
            # 2. Autonomous AI Loop (Institutional-Grade Yield Management)
            sms_active = strategy["enable_sms_day28"]
            midweek_active = strategy["enable_midweek_discount"]
            upsell_active = strategy["enable_bundle_upsell"]
            geo_ads_active = strategy["enable_heb_geo_ads"]
            current_ad_spend = 0.0
            peak_displacement_active = False

            if strategy.get("autonomous_ai_loop", False):
                # On mid-week days (Tue/Wed), activate SMS reminders & WFH discount to shift weekend demand
                if day_of_week in ["Tuesday", "Wednesday"]:
                    midweek_active = True
                    sms_active = True
                
                # On rainy days, activate local H-E-B errand loop ad bursts
                if weather["is_stormy"]:
                    geo_ads_active = True
                    upsell_active = True

                # TRUE PEAK DISPLACEMENT YIELD MANAGEMENT:
                # On peak days (Friday/Saturday), NEVER turn off advertising!
                # Instead, raise the hurdle rate and run top-of-funnel ads specifically to attract Executive Bundle ($75-$85) seekers
                # This actively displaces lower-paying $45 basic cut bookings with high-margin bundle inventory!
                if day_of_week in ["Friday", "Saturday"]:
                    peak_displacement_active = True
                    upsell_active = True
                    geo_ads_active = True # Targeted premium bundle ads

                # DYNAMIC TRIGGER (book-health recruitment mode): if the active book
                # has eroded well below the starting baseline, keep recruiting
                # regardless of day-of-week/weather -- overrides the throttle below.
                current_active_count = sum(1 for c in self.customers if c.status == "ACTIVE")
                recruitment_mode = current_active_count < AI_RECRUITMENT_ACTIVE_COUNT_THRESHOLD
                if recruitment_mode:
                    geo_ads_active = True

                # DYNAMIC TRIGGER (capacity throttle): if people got turned away
                # yesterday, or trailing utilization is already near max, paying to
                # generate more walk-ins is waste -- stop chasing volume and lean on
                # upselling whoever does book instead. Recruitment mode overrides this.
                trailing_utilization = (
                    sum(recent_utilizations) / len(recent_utilizations) if recent_utilizations else 0.0
                )
                capacity_constrained = (
                    prev_day_turnaways > 0 or trailing_utilization > AI_CAPACITY_THROTTLE_UTILIZATION_PCT
                )
                if capacity_constrained and not recruitment_mode:
                    geo_ads_active = False
                    upsell_active = True

            # geo_ads_active ("growth" switch): chase more walk-ins/volume. Subject
            # to the capacity throttle above, since more volume is wasted spend once
            # the chair's already full.
            #
            # salience_maintenance_active (separate "retention" switch): keep the
            # mental-availability carryover topped up even when the growth switch is
            # off. This value comes from lower churn/higher win-back, not from today's
            # walk-in count, so it has no reason to care whether today's chair is full
            # -- deliberately NOT gated by capacity_constrained. Only fires below a
            # salience floor, at reduced spend, so it doesn't just re-become the same
            # always-on switch it's meant to be independent of.
            salience_maintenance_active = (
                strategy.get("autonomous_ai_loop", False)
                and not geo_ads_active
                and self.ad_salience < AI_SALIENCE_MAINTENANCE_FLOOR
            )

            if geo_ads_active or salience_maintenance_active:
                full_budget = strategy.get("daily_ad_budget", 15.0)
                current_ad_spend = full_budget if geo_ads_active else full_budget * AI_SALIENCE_MAINTENANCE_SPEND_FRACTION
                total_ad_spend += current_ad_spend
                # Continuous presence builds mental availability; the reach-quality of
                # today's spend (same saturation curve as the walk-in lift) sets how much.
                reach_quality = (ad_walkin_multiplier(current_ad_spend, self.capacity) - 1.0) / \
                    max(1e-9, self.capacity.ad_response_ceiling - 1.0)
                self.ad_salience = min(1.0, self.ad_salience + AD_SALIENCE_BUILD_RATE_MAX * reach_quality)

            # 3. Calculate Appointment Demand from Active Regulars
            booking_requests = []
            for c in self.customers:
                if c.status == "ACTIVE":
                    wants_to_book = c.evaluate_booking_intent(
                        today_day_of_week=day_of_week,
                        weather_modifier=weather["walk_in_mod"],
                        mid_week_discount_active=midweek_active,
                        sms_reminder_sent=sms_active
                    )
                    if wants_to_book:
                        booking_requests.append(c)

            # 4. Add Walk-in Inquiries
            # Driven by carryover salience (accumulated, decayed prior-day awareness),
            # not by whether an ad happens to be running today -- a passive local-radius
            # awareness ad has no same-day "buy now" mechanism, so a quiet Wednesday
            # right after a Friday/Saturday ad push should still run warmer than a
            # quiet Wednesday after two dark weeks, and vice versa.
            num_walkins = np.random.poisson(3 if day_of_week in ["Friday", "Saturday"] else 1)
            carryover_multiplier = 1.0 + (self.capacity.ad_response_ceiling - 1.0) * carryover_salience
            num_walkins = int(num_walkins * carryover_multiplier)
            num_walkins = int(num_walkins * weather["walk_in_mod"])

            walkin_agents = []
            for _ in range(num_walkins):
                w_agent = CustomerAgent(
                    client_id=next_client_id, is_regular=False, days_since_last_cut=0,
                    price_sensitivity=np.random.beta(2, 5),
                    bundle_receptivity=np.random.beta(4, 3) if peak_displacement_active else np.random.beta(3, 5)
                )
                walkin_agents.append(w_agent)
                next_client_id += 1

            all_demand = booking_requests + walkin_agents

            # 5. Capacity Resolution (Simulating Booksy Calendar slots against realistic 12-cut physical limit)
            max_slots = self.capacity.max_daily_slots # 12 cuts max per day
            actual_bookings = []
            turnaways = 0

            # If Peak Displacement Yield Management is active, prioritize bundle seekers in the queue!
            if peak_displacement_active:
                all_demand.sort(key=lambda x: x.bundle_receptivity, reverse=True)

            for client in all_demand:
                is_bundle = upsell_active and (np.random.random() < client.bundle_receptivity)
                if len(actual_bookings) < max_slots:
                    actual_bookings.append((client, is_bundle))
                else:
                    turnaways += 1

            # 6. True Spendable Take-Home Cash Accounting
            day_revenue = 0.0
            bundle_count = 0
            for client, is_bundle in actual_bookings:
                price = self.capacity.executive_bundle_price if is_bundle else self.capacity.base_service_price
                if midweek_active and day_of_week in ["Tuesday", "Wednesday"]:
                    price -= 10.0 # $10 WFH discount
                day_revenue += price
                if is_bundle: bundle_count += 1
                client.days_since_last_cut = 0
                client.lifetime_spend += price
                client.total_visits += 1
                if client in walkin_agents:
                    # First-time walk-in that got booked today: a walk-in agent is
                    # otherwise a throwaway object created fresh each day, so unless
                    # we start tracking them now they can never come back for the
                    # 2nd visit that promotion to "regular" requires below.
                    self.customers.append(client)
                if not client.is_regular and client.total_visits >= 2:
                    client.is_regular = True

            total_gross_revenue += day_revenue

            # Transaction Frictions & Taxes
            day_cc_fee = day_revenue * self.capacity.credit_card_fee_rate
            day_cogs = (len(actual_bookings) - bundle_count) * self.capacity.cogs_standard_cut + bundle_count * self.capacity.cogs_bundle
            
            day_pretax_profit = day_revenue - day_cc_fee - day_cogs - daily_fixed_overhead - current_ad_spend

            # SE tax and state/city wage tax are flat proportional rates, so they can be
            # accumulated day-by-day without error. Federal income tax is progressive
            # (non-linear) and must be computed once on the annual total — see below.
            day_se_tax = max(0.0, (day_pretax_profit * 0.9235) * self.capacity.self_employment_tax_rate)
            day_state_city_tax = max(0.0, day_pretax_profit * self.capacity.state_city_tax_rate)
            day_net_profit = day_pretax_profit - day_se_tax - day_state_city_tax

            total_cc_fees += day_cc_fee
            total_cogs += day_cogs
            total_se_tax += day_se_tax
            total_state_city_tax += day_state_city_tax
            total_pretax_profit += day_pretax_profit
            total_true_take_home += day_net_profit

            # 7. Advance time & evaluate Churn (and mental-availability-driven win-back)
            for c in self.customers:
                if c.status == "ACTIVE" and c not in [b[0] for b in actual_bookings]:
                    c.days_since_last_cut += 1
                    if np.random.random() < c.calculate_churn_probability(self.ad_salience):
                        c.status = "CHURNED"
                        total_churned += 1
                elif c.status == "CHURNED":
                    # A lapsed client can still be "won back" if the brand remains
                    # mentally available when their next haircut need arises -- the
                    # crux of Sharp's category-entry-point argument. Zero chance if
                    # ads have gone dark long enough for salience to decay to ~0.
                    if np.random.random() < AD_SALIENCE_MAX_REACTIVATION_PROB * self.ad_salience:
                        c.status = "ACTIVE"
                        c.days_since_last_cut = 30  # returns already "due" for a cut
                        total_reactivated += 1

            utilization = (len(actual_bookings) / max_slots) * 100.0
            daily_records.append({
                "day": day, "day_of_week": day_of_week, "is_open": True, "revenue": day_revenue,
                "cc_fee": day_cc_fee, "cogs": day_cogs, "ad_spend": current_ad_spend, "se_tax": day_se_tax,
                "net_profit": day_net_profit, "utilization_pct": min(100.0, utilization),
                "actual_cuts": len(actual_bookings), "bundle_upgrades": bundle_count, "turnaways": turnaways,
                "ad_salience": self.ad_salience
            })

            # Feed today's numbers forward for tomorrow's (or the next open day's) AI decision.
            prev_day_turnaways = turnaways
            recent_utilizations.append(min(100.0, utilization))
            if len(recent_utilizations) > AI_CAPACITY_THROTTLE_WINDOW_DAYS:
                recent_utilizations.pop(0)

        df = pd.DataFrame(daily_records)
        open_df = df[df["is_open"] == True]

        # Federal income tax is progressive (non-linear), so it can only be computed once
        # on the annual total pretax profit -- NOT summed day-by-day like SE/state tax.
        federal_tax = federal_income_tax(
            total_pretax_profit, total_se_tax,
            self.capacity.health_insurance_annual, self.capacity.filing_status
        )
        total_true_take_home -= (federal_tax + self.capacity.health_insurance_annual)

        # Prorate the annual federal tax + health insurance hit across open days
        # (by revenue share) purely so the cumulative take-home chart is smooth.
        if total_gross_revenue > 0:
            lump_sum = federal_tax + self.capacity.health_insurance_annual
            df.loc[df["is_open"], "net_profit"] -= (
                df.loc[df["is_open"], "revenue"] / total_gross_revenue
            ) * lump_sum

        final_active_regulars = sum(1 for c in self.customers if c.status == "ACTIVE")

        summary = {
            "days_worked": len(open_df),
            "total_revenue": total_gross_revenue,
            "total_cc_fees": total_cc_fees,
            "total_cogs": total_cogs,
            "total_ad_spend": total_ad_spend,
            "total_fixed_overhead": open_days_per_year * daily_fixed_overhead,
            "total_se_tax": total_se_tax,
            "total_state_city_tax": total_state_city_tax,
            "total_federal_tax": federal_tax,
            "total_health_insurance": self.capacity.health_insurance_annual,
            "total_net_profit": total_true_take_home, # True spendable cash
            "avg_utilization_pct": open_df["utilization_pct"].mean() if len(open_df) > 0 else 0.0,
            "aov": total_gross_revenue / max(1, df["actual_cuts"].sum()),
            "total_cuts": df["actual_cuts"].sum(),
            "total_bundles": df["bundle_upgrades"].sum(),
            "total_turnaways": df["turnaways"].sum(),
            "total_churned": total_churned,
            "total_reactivated": total_reactivated,
            "final_active_regulars": final_active_regulars,
            "final_ad_salience": self.ad_salience,
            "daily_df": df
        }
        return {"daily_df": df, "summary": summary}

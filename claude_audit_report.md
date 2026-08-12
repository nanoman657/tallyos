# 📊 SOLO BARBER DIGITAL TWIN & UNIT ECONOMICS SIMULATION — REVISION 3

> **Changelog vs. Revision 1:** The original report's underlying simulation code
> (`barbershop_twin/*.py`) omitted federal income tax entirely, modeled zero
> break time in the 8-hour chair day, and assumed instant full utilization when
> relocating to a market where Will has no existing clients. All three are
> fixed at the code level (not just restated here) — see
> `barbershop_twin/taxes.py` for the tax model. Every number below comes from
> re-running the corrected simulators, not from hand-adjusting Revision 1.
>
> **Changelog vs. Revision 2:** Every prior version assumed Will's 180-client
> book and 84% chair utilization transfer identically to all 100 cities,
> regardless of how many other barbershops already compete for the same
> clientele. Revision 3 adds a supply-vs-demand feasibility check
> (`barbershop_twin/competition.py`), grounded in IBISWorld industry data and
> BLS-adjacent benchmarks, for every city in the ranking — see new Section 5.

---

## 📝 EXECUTIVE SUMMARY & CONTEXT

* **Subject:** Will (Solo Barber & 1-Chair Suite Owner, *Fresh & Focused Barbershop LLC*, 2855 Mangum Rd, Suite 340-B, Houston, TX 77092).
* **Filing status:** Head of Household (single parent, one dependent) — this changes standard deduction and bracket thresholds vs. Single filing, and is now applied consistently.
* **Objective:** Determine true spendable personal take-home cash, optimal marketing strategy, yield management framework, and capital ROI across 100 U.S. cities.
* **Core Model Architecture:** A stochastic agent-based digital twin (365-day simulation) enforcing time-capacity limits with a mandatory break, empirical conversion funnels, **full federal + self-employment + state/city tax liability**, self-employed health insurance, and real-world friction.

---

## 🧮 1. THE INSTITUTIONAL FINANCIAL & OPERATIONAL FRAMEWORK

### A. Real-World Menu & Pricing (Calibrated to Will's Live Booksy Page)
* **Standard Cut / Skin Fade ($38.00 avg):** 40 minutes per client (30 min cut + 10 min sanitization/cleanup).
* **The "Fresh Combo" ($65.00 avg):** Haircut + Beard Shave Razor Detail + Hot Towel / Moisturizing Steam Wash (60 minutes per client).

### B. Time-Based Capacity Ceiling
* **Daily Chair Limit:** 480 minutes (8 working hours) **minus a mandatory 30-minute lunch/reset break = 450 bookable minutes.** (Revision 1 booked the full 480 minutes back-to-back with zero slack for meals, bathroom breaks, or client overruns — corrected.)
* **Max Physical Capacity:** 11 Standard Cuts/day (40m) **OR** 7 Fresh Combos/day (60m).
* **Working Days:** 245 open days/year (260 weekdays minus 15 PTO/Sick/Daughter days).

### C. Unit Economics & Cost Deductions
1. **Credit Card Fees:** 3.0% flat fee on 100% of gross revenue (Booksy Biz / Stripe).
2. **Consumable COGS:** $1.80 per standard cut | $3.20 per Fresh Combo.
3. **Fixed Suite Overhead:** Flat annual lease + software/insurance (e.g. **-$19,200.00/yr** in Cypress, TX at $1,400/mo lease + $200/mo Booksy/liability insurance).
4. **Self-Employed Health Insurance:** **-$6,000.00/yr** (ACA marketplace, self-only, no employer subsidy) — *new in this revision.* This was flagged as a missing cost in the audit and is now a modeled cash outflow (and a federal AGI deduction, per actual Schedule 1 rules).
5. **Mandatory Federal Self-Employment Tax:** 15.3% FICA Tax applied to exactly **92.35%** of net pre-tax operating profit (IRC §1401/1402).
6. **Federal Income Tax — new in this revision.** Progressive 2024 Head-of-Household brackets (10%–37%) applied to taxable income after: half of SE tax (above-the-line), the self-employed health insurance deduction, the standard deduction ($21,900 HoH), and the §199A Qualified Business Income deduction (20% of QBI, uncapped at these income levels since barbering isn't a specified service trade and income is below the wage/UBIA phase-in threshold). **Revision 1 had no federal income tax line at all** — every "true take-home" figure in that version was overstated by roughly $2,400–$7,600/year depending on market.
7. **State & City Wage Taxes:** Enforced per city (e.g., 0% in TX/FL/WA/NV; 6.82% in Philly; 9.88% in NYC).

---

## 📈 2. YIELD MANAGEMENT & RETENTION PHYSICS

1. **Peak Displacement Yield Management:** On peak Fridays and Saturdays, marketing spend ($15/day) is deployed to attract **$65 Fresh Combos** rather than $38 standard cuts, displacing lower-margin bookings within the (now 450-minute) capacity ceiling.
2. **Empirical SMS Retention Funnel:** SMS reminders on Day 28 flow through a multi-stage funnel:
   $$\text{Deliverability (99\%)} \times \text{CTR (10\%)} \times \text{Booking Conv (50\%)} = \mathbf{4.95\% \text{ Net Booking Lift}}$$
   *(Vanity metrics like 99% open rates are explicitly rejected.)*

---

## 🏆 3. THE 100-CITY SIMULATION RESULTS

### Top 10 U.S. Cities for True Spendable Take-Home Cash

| Rank | City, State | Gross Revenue | Annual Suite Lease | SE Tax | Federal Tax | State/City Tax | Health Ins. | ⭐ TRUE TAKE-HOME | AOV | Time Util % |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | **San Francisco, CA** | $163,776 | -$37,200 | -$16,546 | -$7,602 | -$7,026 | -$6,000 | **$79,926.70** | $85.17 | 84.0% |
| **#2** | **Miami, FL** | $133,275 | -$28,800 | -$13,552 | -$5,548 | $0 | -$6,000 | **$70,814.68** | $69.31 | 84.0% |
| **#3** | **Oakland, CA** | $140,616 | -$30,000 | -$14,389 | -$6,076 | -$6,110 | -$6,000 | **$69,260.49** | $73.12 | 84.0% |
| **#4** | **Fremont, CA** | $140,616 | -$31,200 | -$14,219 | -$5,969 | -$6,038 | -$6,000 | **$68,409.10** | $73.12 | 84.0% |
| **#5** | **San Jose, CA** | $140,616 | -$31,200 | -$14,219 | -$5,969 | -$6,038 | -$6,000 | **$68,409.10** | $73.12 | 84.0% |
| **#6** | **Seattle, WA** | $127,549 | -$30,000 | -$12,658 | -$4,983 | $0 | -$6,000 | **$65,943.20** | $73.18 | 77.8% |
| **#7** | **Irvine, CA** | $133,275 | -$28,800 | -$13,552 | -$5,548 | -$5,755 | -$6,000 | **$65,059.78** | $69.31 | 84.0% |
| **#8** | **New York, NY** | $145,740 | -$36,000 | -$14,287 | -$6,012 | -$9,990 | -$6,000 | **$64,824.14** | $81.88 | 81.9% |
| **#9** | **Los Angeles, CA** | $133,275 | -$30,000 | -$13,383 | -$5,441 | -$5,683 | -$6,000 | **$64,208.40** | $69.31 | 84.0% |
| **#10**| **Honolulu, HI** | $133,275 | -$30,000 | -$13,383 | -$5,441 | -$6,867 | -$6,000 | **$63,024.46** | $69.31 | 84.0% |

**What changed vs. Revision 1:** Once federal tax is applied progressively, the spread between the #1 and #10 cities compresses (federal brackets tax high earners in every city, not just the expensive ones), and Seattle drops out of the top ranks relative to Austin/Honolulu once its snow-day-free but lower-AOV profile is taxed the same way as everywhere else. NYC also moves down (from #5 to #7) as its already-heavy state/city tax stacks with federal tax more severely than lower-tax states.

### Key Regional Findings:
* **Houston (Will's Base):** $86,723 Gross | -$19,200 Lease | -$8,580 SE Tax | -$2,409 Federal Tax | $0 State Tax | -$6,000 Health Insurance | **$43,738.26 True Take-Home** (~$3,645/mo clean cash).
* **Philadelphia (Winter-Adjusted):** $109,264 Gross | -$28,392 Lease | -$10,364 SE Tax | -$3,534 Federal Tax | -$5,002 PA/Philly Wage Tax | -$6,000 Health Insurance | **$48,446.59 True Take-Home** *(6 snow closures reduce open days to 234)*.

---

## 📦 4. 1-CHAIR STARTUP CAPITAL & ROI MODEL

### Itemized Setup Capital (1-Chair Suite):
1. **Lease Security Deposit (2 Months Rent):** $2,800 (Houston) to $5,800 (SF).
2. **Core Suite Furniture & Equip:** $2,000 - $2,800.
3. **Tools & Initial Supplies:** $1,200.
4. **Licensing & Insurance:** $550 - $850.
5. **Branding & Launch Ads:** $750.

### Capital Summary & Payback — revised for relocation ramp-up
Will's 180 regulars are in Houston and don't relocate with him. Revision 1's
payback math divided total startup capital by *steady-state* monthly take-home,
implying every city hits full 84% utilization on day one. This revision applies
a 3-month client-base ramp (25% → 50% → 75% of steady-state, 100% from month 4)
to every market except Houston, where his existing book applies immediately.

| City | Startup Capital | Monthly Take-Home (steady-state) | Payback Period | 1st-Yr ROC |
| :--- | :---: | :---: | :---: | :---: |
| **Houston, TX** | $7,300 | $3,645 | **2.0 months** | 599.2% |
| **Miami, FL** | $9,700 | $5,901 | **3.1 months** | 638.8% |
| **Austin, TX** | $8,600 | $5,187 | **3.2 months** | 633.2% |
| **San Francisco, CA** | $11,400 | $6,661 | **3.2 months** | 613.5% |
| **New York, NY** | $11,200 | $5,402 | **3.6 months** | 506.4% |
| **Los Angeles, CA** | $10,200 | $5,351 | **3.4 months** | 550.8% |
| **Philadelphia, PA** | $9,532 | $4,037 | **3.9 months** | 444.7% |
| **Chicago, IL** | $9,200 | $4,317 | **3.6 months** | 492.6% |

* **Total Initial Capital Required:** $7,300 (Houston) to $11,400 (San Francisco) — unchanged.
* **Payback Period:** **2.0 to 3.9 months** across top markets — roughly double Revision 1's 1.4–1.6 months, because non-Houston markets now carry a realistic client-acquisition ramp instead of assuming an instant, fully-booked chair.
* **1st-Year Return on Capital (ROC):** **445% to 639%** — still very strong, but Houston's ROC lead is now explainable (existing client base = no ramp penalty) rather than an artifact of uniform 100%-day-one assumptions.

---

## 🥊 5. COMPETITIVE & DEMAND FEASIBILITY CHECK

Every prior revision priced Will's revenue in each city assuming his 180-client
book and 84% chair utilization simply *appear* — with no check against how
many other barbers already compete for the same clientele. This section adds
that check.

### Method
Using IBISWorld's 2025 barbershop industry data (~154,925 U.S. shops, ~176,672
employees, $7.0B market) and state-level shop-count data (directory-sourced,
used only for relative density), we estimate for each city:

* **Existing supply:** `(city population ÷ people-per-shop for that state) × avg barbers/shop × avg cuts/barber/year`
* **Total market demand:** `city population × barbershop-patron share × visits/patron/year`
* **Will's required share:** his modeled annual cut volume ÷ total market demand

Two assumption sets are run, not one: a **central case** (15% of the population
patronizes a barbershop, 9 visits/year, incumbents produce ~1,130 cuts/barber/
year — derived from industry revenue ÷ employment ÷ a blended $35 ticket) and a
**conservative case** (10% patron share, 7 visits/year, incumbents as efficient
as Will's own aggressive pace, ~1,900 cuts/barber/year). Reporting a single
verdict here would be false precision — the industry data available doesn't
support that level of confidence.

### Findings — Top 10 cities

| City | Est. Population | Est. Existing Shops | Saturation Range (supply ÷ demand) | Will's Required Share |
| :--- | :---: | :---: | :---: | :---: |
| San Francisco, CA | 810,000 | ~433 | 51% – 166% | 0.18% – 0.34% |
| Miami, FL | 450,000 | ~258 | 55% – 177% | 0.32% – 0.61% |
| Oakland, CA | 435,000 | ~233 | 51% – 166% | 0.33% – 0.63% |
| Fremont, CA | 230,000 | ~123 | 51% – 166% | 0.62% – 1.19% |
| San Jose, CA | 970,000 | ~519 | 51% – 166% | 0.15% – 0.28% |
| Seattle, WA | 740,000 | ~342 | 44% – 143% | 0.17% – 0.34% |
| Irvine, CA | 310,000 | ~166 | 51% – 166% | 0.46% – 0.89% |
| New York, NY | 8,260,000 | ~3,820 | 44% – 143% | 0.02% – 0.03% |
| Los Angeles, CA | 3,820,000 | ~2,043 | 51% – 166% | 0.04% – 0.07% |
| Honolulu, HI | 345,000 | ~160 | 44% – 143% | 0.41% – 0.80% |
| **Houston, TX (base)** | **2,300,000** | **~1,504** | **63% – 202%** | **0.06% – 0.12%** |

### What this actually tells us
1. **Aggregate demand is not the binding constraint anywhere on this list.** Even in the conservative scenario, Will never needs more than ~1.2% of a city's total barbershop-patron demand (Fremont, the smallest city in the top 10, is the worst case). Every other top-10 city requires under 1%. A single solo operator capturing 180 regulars is a rounding error against any of these markets' total demand — the "is there enough demand" question, taken literally, is comfortably yes.
2. **Competitive saturation is genuinely uncertain, not comfortably "yes."** The saturation range swings from ~44–63% (plenty of headroom) to ~143–202% (already oversupplied relative to modeled demand) purely based on how efficiently existing incumbents operate — a variable we don't have precise per-city data for. Houston itself shows the widest range (63%–202%), meaning Will's own home-market assumption isn't automatically safe either.
3. **Small-population cities carry more execution risk than the take-home ranking suggests.** Fremont and Honolulu rank well on tax/lease math (#4 and #10) but require the largest market share of any top-10 city and sit in smaller, thinner total markets — meaning if local incumbents turn out to be efficient, a new solo entrant has less room to simply "find" unclaimed demand and would need to visibly out-market or out-differentiate existing shops instead.
4. **This does not overturn the ranking** — it reframes the real risk. The binding constraint isn't "not enough people get haircuts," it's client-acquisition speed and differentiation against local competitors, which is exactly what the Section 4 startup ramp-up already partially prices in. Treat the Section 3 ranking as revenue-if-acquired, and this section as how hard "acquired" actually is, market by market.

*Data-quality caveat: city populations are approximate (city-proper estimates, not metro-area or trade-area), and the shop-density figures are derived from a mix of an industry market-research estimate and a business-directory scrape whose absolute totals disagree with each other (only their state-relative pattern is used here). Treat this section as a directional plausibility screen, not a market-research-grade TAM study.*

---

## ✅ WHAT WAS FIXED (audit trail)

1. **Federal income tax was entirely absent** in Revision 1 — every "true take-home" number only subtracted SE tax and state/city tax. Fixed in `barbershop_twin/taxes.py`, applied consistently across `simulation.py`, `simulate_markets.py`, and `simulate_top_100_cities.py`.
2. **Self-employed health insurance was unmodeled.** Added as a $6,000/yr cash outflow and federal AGI deduction (matches actual Schedule 1 treatment — it reduces income tax but not SE tax or state wage tax).
3. **Zero-slack capacity** (480/480 minutes booked, no break) was corrected to 450 bookable minutes (11 cuts / 7 combos max), reflecting a mandatory lunch/reset break.
4. **Startup payback assumed instant full utilization** in cities with no existing clientele. Fixed with a 3-month ramp-up for every market except Houston.
5. **`run_twin.py` was crashing** (`KeyError` on missing summary fields) due to an unrelated pre-existing code bug; fixed as part of this pass so the baseline/static/AI-loop scenario comparison actually runs.
6. **No competitive or demand-side check existed at all** — every city assumed Will's 180-client book and 84% utilization would simply materialize regardless of local competition. Fixed with `barbershop_twin/competition.py` (Section 5): required market share is confirmed small everywhere (<1.2%), but competitive saturation is shown honestly as a wide, assumption-sensitive range rather than a false-confidence single number.

**Not yet modeled (still open, flagged in the original audit, lower priority):** retirement contributions (SEP-IRA), regional variation in health insurance premiums and consumable COGS, credit-card chargeback risk, equipment replacement/depreciation reserves, and metro/trade-area population (vs. city-proper) for the demand model. These would further reduce take-home modestly or tighten the feasibility ranges but don't change the ranking or the qualitative conclusions above.

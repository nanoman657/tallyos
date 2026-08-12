/* app.js - Tethered Institutional-Grade Client-Side System Dynamics Simulation Engine
 * Calibrated to Will's Live Booksy Menu at Fresh & Focused Barbershop LLC (Houston, TX):
 * $38 Standard Cuts (40m) | $65 Fresh Combos (60m) | Strict Arithmetic & Time-Based Utilization.
 */

// STATE & CHARTS
let profitChartInstance = null;
let utilChartInstance = null;

// GEOGRAPHIC MARKET CONFIGURATIONS (Calibrated to Live Booksy Menu & US 2025 Benchmarks)
const MARKET_CONFIGS = {
    heights: {
        name: "Houston Heights, TX (77008)",
        basePrice: 38.0, // Live Booksy Menu ($35 Fresh Cut / $40 Skin Fade)
        bundlePrice: 65.0, // Live Booksy Menu ($60 Fresh Combo + $25 Steam Wash / Facial add-ons)
        monthlyLease: 1750.0, // All-in suite lease
        monthlySoftware: 200.0, // Booksy Biz ($130) + liability insurance ($70)
        taxRate: 0.0, // 0% TX State Tax
        isPhillyWinter: false,
        walkinAvg: 2,
        bundleRateMod: 1.0,
        baselineProfit: 55200.00,
        baselineRev: 93800.00
    },
    cypress: {
        name: "Cypress, TX (Will's Live Booksy)",
        basePrice: 38.0, // Live Booksy Menu ($35 Fresh Cut / $40 Skin Fade)
        bundlePrice: 65.0, // Live Booksy Menu ($60 Fresh Combo + $25 Steam Wash / Facial add-ons)
        monthlyLease: 1400.0, // All-in suburban lease (~$325/wk; Wi-Fi & utilities baked in)
        monthlySoftware: 200.0, // Booksy Biz ($130) + liability insurance ($70)
        taxRate: 0.0, // 0% TX State Tax
        isPhillyWinter: false,
        walkinAvg: 2, // Car-dependent suburban center
        bundleRateMod: 1.15, // High father/son combo & beard demand
        baselineProfit: 55200.00,
        baselineRev: 93800.00
    },
    philly: {
        name: "Philadelphia, PA (Winter Studio)",
        basePrice: 48.0, // Higher East Coast urban pricing
        bundlePrice: 80.0, // Urban Executive Combo pricing
        monthlyLease: 2166.0, // Prime urban studio lease (~$500/wk; Wi-Fi & utilities baked in)
        monthlySoftware: 200.0, // Booksy Biz ($130) + liability insurance ($70)
        taxRate: 0.0682, // PA State Tax (3.07%) + Philly City Wage Tax (3.75%)
        isPhillyWinter: true,
        walkinAvg: 4, // High walkable pedestrian foot traffic
        bundleRateMod: 1.25, // Urban tech/creative professionals upgrading to hot-towel shaves
        baselineProfit: 63500.00,
        baselineRev: 118400.00
    }
};

let CURRENT_MARKET = "heights";

// FEDERAL TAX MODEL (mirrors barbershop_twin/taxes.py)
// Previously this dashboard, like the Python simulators it's tethered to, only
// modeled SE tax + state/city wage tax and omitted federal income tax entirely,
// which overstated "true spendable take-home" for every market. Head of
// Household filing status (2024 brackets) since Will files as a single parent.
const HEALTH_INSURANCE_ANNUAL = 6000.0; // Self-employed ACA marketplace premium, no employer subsidy
const STANDARD_DEDUCTION_HOH = 21900.0;
const QBI_RATE = 0.20;
const FEDERAL_BRACKETS_HOH = [
    [16550, 0.10], [63100, 0.12], [100500, 0.22], [191950, 0.24],
    [243700, 0.32], [609350, 0.35], [Infinity, 0.37]
];

function applyBrackets(taxableIncome) {
    let tax = 0.0;
    let prevCeiling = 0.0;
    for (const [ceiling, rate] of FEDERAL_BRACKETS_HOH) {
        if (taxableIncome <= prevCeiling) break;
        const sliceAmount = Math.min(taxableIncome, ceiling) - prevCeiling;
        tax += sliceAmount * rate;
        prevCeiling = ceiling;
    }
    return tax;
}

function federalIncomeTax(netProfit, seTax, healthInsuranceAnnual) {
    if (netProfit <= 0) return 0.0;
    const agi = Math.max(0.0, netProfit - (seTax / 2.0) - healthInsuranceAnnual);
    const taxableBeforeQbi = Math.max(0.0, agi - STANDARD_DEDUCTION_HOH);
    const qbiBase = Math.max(0.0, netProfit - (seTax / 2.0));
    const qbiDeduction = Math.min(QBI_RATE * qbiBase, QBI_RATE * taxableBeforeQbi);
    const taxableIncome = Math.max(0.0, taxableBeforeQbi - qbiDeduction);
    return applyBrackets(taxableIncome);
}

// INITIALIZE ON LOAD
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    setupEventListeners();
    runSimulation();
});

function setupEventListeners() {
    const sliders = [
        { id: 'lever-sms', valId: 'val-sms', suffix: '%' },
        { id: 'lever-discount', valId: 'val-discount', prefix: '$' },
        { id: 'lever-bundle', valId: 'val-bundle', suffix: '%' },
        { id: 'lever-ads', valId: 'val-ads', prefix: '$' }
    ];

    sliders.forEach(s => {
        const input = document.getElementById(s.id);
        const display = document.getElementById(s.valId);
        input.addEventListener('input', (e) => {
            let val = e.target.value;
            display.innerText = (s.prefix || '') + val + (s.suffix || '');
            if (!document.getElementById('ai-loop-toggle').checked) {
                runSimulation();
            }
        });
    });

    const marketSelect = document.getElementById('market-select');
    if (marketSelect) {
        marketSelect.addEventListener('change', (e) => {
            CURRENT_MARKET = e.target.value;
            runSimulation();
        });
    }

    document.getElementById('ai-loop-toggle').addEventListener('change', (e) => {
        const isAI = e.target.checked;
        if (isAI) {
            document.getElementById('lever-sms').value = 85;
            document.getElementById('val-sms').innerText = '85% (AI Opt)';
            document.getElementById('lever-discount').value = 10;
            document.getElementById('val-discount').innerText = '$10 (AI Opt)';
            document.getElementById('lever-bundle').value = 35;
            document.getElementById('val-bundle').innerText = '35% (AI Opt)';
            document.getElementById('lever-ads').value = 15;
            document.getElementById('val-ads').innerText = '$15 (AI Opt)';
        }
        runSimulation();
    });

    document.querySelectorAll('.env-checkbox input').forEach(cb => {
        cb.addEventListener('change', () => runSimulation());
    });

    document.getElementById('run-sim-btn').addEventListener('click', () => {
        runSimulation();
    });
}

// TETHERED CLIENT-SIDE STOCHASTIC SIMULATION (365 DAYS)
function runSimulation() {
    const isAI = document.getElementById('ai-loop-toggle').checked;
    const mkt = MARKET_CONFIGS[CURRENT_MARKET] || MARKET_CONFIGS.heights;
    
    const smsRate = parseInt(document.getElementById('lever-sms').value) / 100.0;
    const discountAmt = parseInt(document.getElementById('lever-discount').value);
    const bundleRate = (parseInt(document.getElementById('lever-bundle').value) / 100.0) * mkt.bundleRateMod;
    const adSpendDaily = parseInt(document.getElementById('lever-ads').value);

    const hasSummer = document.getElementById('env-summer').checked;
    const hasStorms = document.getElementById('env-storms').checked;
    const hasHEB = document.getElementById('env-heb').checked;

    const days = 365;
    const maxDailyMinutes = 480 - 30; // 8 hours minus mandatory 30-min lunch/reset break
    const minPerStandard = 40;   // 40 mins per standard cut
    const minPerCombo = 60;      // 60 mins per Fresh Combo
    
    const basePrice = mkt.basePrice;
    const bundlePrice = mkt.bundlePrice;
    const barberSplit = 1.0; 
    const openDaysPerYear = 245; 
    const totalWeekdays = 260;

    // STRICT ANNUAL OVERHEAD TETHERING: Exactly 12 months of all-in lease + software/insurance
    const totalAnnualOverhead = (mkt.monthlyLease + mkt.monthlySoftware) * 12.0;
    const dailyOverheadRate = totalAnnualOverhead / float(totalWeekdays);

    const ccRate = 0.030; // 3.0% Booksy Biz / Stripe processing fee
    const cogsStandard = 1.80; // Neck strip, clipper spray, cape laundry, blades
    const cogsBundle = 3.20;   // Fresh razor blade, hot towels, steam water, beard oil, balm
    const seTaxRate = 0.153;   // Mandatory 15.3% Federal Self-Employment (FICA) Tax

    let totalRev = 0;
    let totalAds = 0;
    let totalPreTaxProfit = 0;
    let totalTakeHome = 0;
    let totalTaxes = 0;
    let totalCuts = 0;
    let totalBundles = 0;
    let totalTurnaways = 0;
    let totalMinutesWorked = 0;
    let daysWorked = 0;

    let dailyProfits = [];
    let dayRevenues = [];
    let cumulativeProfits = [];
    let baselineCumulative = [];
    let dailyUtils = [];
    let rollingUtils = [];

    let currentClients = 180;
    let churnedCount = 0;

    for (let day = 1; day <= days; day++) {
        const dayOfWeek = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][(day - 1) % 7];
        
        if (dayOfWeek === "Mon" || dayOfWeek === "Sun") {
            dailyProfits.push(0);
            dayRevenues.push(0);
            dailyUtils.push(0);
            if (day === 1) {
                cumulativeProfits.push(0);
                baselineCumulative.push(0);
            } else {
                cumulativeProfits.push(cumulativeProfits[cumulativeProfits.length - 1]);
                baselineCumulative.push(baselineCumulative[baselineCumulative.length - 1]);
            }
            continue;
        }

        // REALISTIC PHILLY WINTER CLOSURES: Severe snowstorms / blizzards force 6-7 full shop closures per year
        const isWinterPeriod = mkt.isPhillyWinter && (day <= 60 || day >= 335);
        const isSevereSnowstorm = isWinterPeriod && (Math.random() < 0.12);

        if (isSevereSnowstorm || daysWorked >= openDaysPerYear || (Math.random() < (15.0 / 260.0))) {
            dailyProfits.push(-dailyOverheadRate);
            dayRevenues.push(0);
            dailyUtils.push(0);
            let prevCum = cumulativeProfits.length > 0 ? cumulativeProfits[cumulativeProfits.length - 1] : 0;
            cumulativeProfits.push(prevCum - dailyOverheadRate);
            let dailyBaseStep = mkt.baselineProfit / openDaysPerYear;
            let prevBase = baselineCumulative.length > 0 ? baselineCumulative[baselineCumulative.length - 1] : 0;
            baselineCumulative.push(prevBase + dailyBaseStep);
            continue;
        }

        daysWorked++;

        const isSummerDay = hasSummer && !mkt.isPhillyWinter && (day >= 150 && day <= 250);
        const isStormDay = hasStorms && (Math.random() < 0.15);
        const isWinterSlushDay = isWinterPeriod && not(isSevereSnowstorm) && (Math.random() < 0.40);
        
        let weatherMod = 1.0;
        if (isWinterSlushDay) weatherMod = 0.35; // 65% drop in walk-ins and cancellations in sub-freezing slush!
        else if (isStormDay) weatherMod = 0.70;
        
        const beardMod = isSummerDay && !isStormDay ? 1.25 : 1.0;

        const isPeakDay = dayOfWeek === "Fri" || dayOfWeek === "Sat";
        let activeAdSpend = adSpendDaily;
        let effectiveBundleRate = bundleRate;

        if (isAI) {
            if (isPeakDay) {
                activeAdSpend = 15.0; 
                effectiveBundleRate = Math.min(0.85, bundleRate * 1.40); 
            } else if (dayOfWeek in ["Tue", "Wed"] || isStormDay || isWinterSlushDay) {
                activeAdSpend = 15.0; 
            } else {
                activeAdSpend = 0.0;
            }
        }
        totalAds += activeAdSpend;

        let baseDemand = (currentClients / 28.0) * weatherMod * beardMod;
        if ((dayOfWeek === "Tue" || dayOfWeek === "Wed") && discountAmt > 0) {
            baseDemand *= (1.0 + (discountAmt / 15.0) * 0.5);
        }

        if (smsRate > 0) {
            baseDemand *= (1.0 + smsRate * 0.05); 
        }

        let walkins = 0;
        if (hasHEB || mkt.isPhillyWinter) {
            walkins = isPeakDay ? mkt.walkinAvg : Math.max(1, mkt.walkinAvg - 1);
            if (activeAdSpend > 0) walkins = Math.round(walkins * (isPeakDay ? 1.8 : 2.0));
            walkins = Math.round(walkins * weatherMod);
        }

        let totalDemandClients = Math.round(baseDemand + walkins);
        
        // TIME-CAPACITY YIELD MANAGEMENT LOOP (480 MINS DAILY):
        let dayStandard = 0;
        let dayBundles = 0;
        let dayMins = 0;
        
        let desiredBundles = Math.min(totalDemandClients, Math.round(totalDemandClients * (effectiveBundleRate * beardMod)));
        let desiredStandard = Math.max(0, totalDemandClients - desiredBundles);
        
        if (isPeakDay) {
            while (desiredBundles > 0 && (dayMins + minPerCombo) <= maxDailyMinutes) {
                dayBundles++;
                dayMins += minPerCombo;
                desiredBundles--;
            }
            while (desiredStandard > 0 && (dayMins + minPerStandard) <= maxDailyMinutes) {
                dayStandard++;
                dayMins += minPerStandard;
                desiredStandard--;
            }
        } else {
            while (desiredStandard > 0 && (dayMins + minPerStandard) <= maxDailyMinutes) {
                dayStandard++;
                dayMins += minPerStandard;
                desiredStandard--;
            }
            while (desiredBundles > 0 && (dayMins + minPerCombo) <= maxDailyMinutes) {
                dayBundles++;
                dayMins += minPerCombo;
                desiredBundles--;
            }
        }

        let unserved = desiredBundles + desiredStandard;
        if (unserved > 0) totalTurnaways += unserved;

        let actualCuts = dayStandard + dayBundles;
        let cutPrice = basePrice;
        if ((dayOfWeek === "Tue" || dayOfWeek === "Wed") && discountAmt > 0) {
            cutPrice -= discountAmt;
        }

        let dayRev = (dayStandard * cutPrice) + (dayBundles * (bundlePrice - (discountAmt > 0 ? discountAmt : 0)));
        let houseGross = dayRev * barberSplit;
        
        let dayCcFee = dayRev * ccRate;
        let dayCogs = (dayStandard * cogsStandard) + (dayBundles * cogsBundle);
        let netDayPreTax = houseGross - dayCcFee - dayCogs - dailyOverheadRate - activeAdSpend;
        
        let daySeTax = Math.max(0.0, (netDayPreTax * 0.9235) * seTaxRate);
        let dayStateCityTax = Math.max(0.0, netDayPreTax * mkt.taxRate);
        let netDayProfit = netDayPreTax - daySeTax - dayStateCityTax;

        totalRev += dayRev;
        totalPreTaxProfit += netDayPreTax;
        totalTakeHome += netDayProfit;
        totalTaxes += (daySeTax + dayStateCityTax);
        totalCuts += actualCuts;
        totalBundles += dayBundles;
        totalMinutesWorked += dayMins;

        let utilPct = Math.min(100.0, (dayMins / float(maxDailyMinutes)) * 100.0);

        dailyProfits.push(netDayProfit);
        dayRevenues.push(dayRev);
        dailyUtils.push(utilPct);

        let prevCum = cumulativeProfits.length > 0 ? cumulativeProfits[cumulativeProfits.length - 1] : 0;
        cumulativeProfits.push(prevCum + netDayProfit);

        let dailyBaseStep = mkt.baselineProfit / openDaysPerYear;
        let prevBase = baselineCumulative.length > 0 ? baselineCumulative[baselineCumulative.length - 1] : 0;
        baselineCumulative.push(prevBase + dailyBaseStep);

        let dailyChurnRate = 0.0018 * (1.0 - (smsRate * 0.25));
        if (isStormDay || isWinterSlushDay) dailyChurnRate *= 1.2;
        let lostToday = Math.round(currentClients * dailyChurnRate);
        churnedCount += lostToday;
        currentClients = Math.max(90, currentClients - lostToday + Math.round(walkins * 0.3));
    }

    // STRICT ARITHMETIC TETHERING RE-CALCULATION:
    let tetheredCcFees = totalRev * ccRate;
    let tetheredCogs = (totalCuts - totalBundles) * cogsStandard + totalBundles * cogsBundle;
    let tetheredPreTax = totalRev - tetheredCcFees - tetheredCogs - totalAnnualOverhead - totalAds;
    let tetheredSeTax = Math.max(0.0, (tetheredPreTax * 0.9235) * seTaxRate);
    let tetheredStateTax = Math.max(0.0, tetheredPreTax * mkt.taxRate);
    let tetheredFedTax = federalIncomeTax(tetheredPreTax, tetheredSeTax, HEALTH_INSURANCE_ANNUAL);
    let tetheredTakeHome = tetheredPreTax - tetheredSeTax - tetheredStateTax - tetheredFedTax - HEALTH_INSURANCE_ANNUAL;

    // Federal tax + health insurance are annual/non-linear; prorate across the
    // daily cumulative chart by revenue share (SE/state tax already accumulated
    // day-by-day above since those are flat proportional rates).
    if (totalRev > 0) {
        const lumpSum = tetheredFedTax + HEALTH_INSURANCE_ANNUAL;
        let runningCum = 0;
        for (let i = 0; i < dailyProfits.length; i++) {
            const dayRevShare = dayRevenues[i] / totalRev;
            runningCum += dailyProfits[i] - (dayRevShare * lumpSum);
            cumulativeProfits[i] = runningCum;
        }
    }

    // TETHERED TIME UTILIZATION:
    let tetheredUtilPct = (totalMinutesWorked / (daysWorked * maxDailyMinutes)) * 100.0;

    for (let i = 0; i < dailyUtils.length; i++) {
        let start = Math.max(0, i - 30);
        let slice = dailyUtils.slice(start, i + 1);
        let avg = slice.reduce((a, b) => a + b, 0) / slice.length;
        rollingUtils.push(avg);
    }

    updateDashboardUI({
        market: mkt,
        revenue: totalRev,
        barberPayout: 0.0,
        adSpend: totalAds,
        netProfit: tetheredTakeHome,
        taxes: (tetheredSeTax + tetheredStateTax + tetheredFedTax),
        utilization: tetheredUtilPct,
        aov: totalCuts > 0 ? totalRev / totalCuts : basePrice,
        bundles: totalBundles,
        churn: churnedCount,
        clients: currentClients,
        cumulativeProfits: cumulativeProfits,
        baselineCumulative: baselineCumulative,
        rollingUtils: rollingUtils
    });
}

function float(val) { return Number(val); }
function not(val) { return !val; }

function updateDashboardUI(data) {
    const mkt = data.market;
    document.getElementById('kpi-profit').innerText = `$${Math.round(data.netProfit).toLocaleString()}`;
    let diff = data.netProfit - mkt.baselineProfit;
    let diffElem = document.getElementById('kpi-profit-diff');
    diffElem.innerText = (diff >= 0 ? `+$${Math.round(diff).toLocaleString()}` : `-$${Math.round(Math.abs(diff)).toLocaleString()}`) + ` vs ${mkt.name.split(',')[0]} Base`;
    diffElem.className = `kpi-diff ${diff >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('kpi-revenue').innerText = `$${Math.round(data.revenue).toLocaleString()}`;
    document.getElementById('kpi-barbers').innerText = `100% (Solo Owner) | Tax: ${((0.153 + mkt.taxRate) * 100).toFixed(1)}%`;
    document.getElementById('kpi-aov').innerText = `$${data.aov.toFixed(2)}`;
    document.getElementById('kpi-bundles-cnt').innerText = data.bundles.toLocaleString();
    document.getElementById('kpi-util').innerText = `${data.utilization.toFixed(1)}%`;
    document.getElementById('kpi-churn').innerText = data.churn;

    document.getElementById('tbl-rev').innerText = `$${data.revenue.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    let revDiff = data.revenue - mkt.baselineRev;
    document.getElementById('tbl-rev-diff').innerText = (revDiff >= 0 ? "+" : "") + `$${revDiff.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById('tbl-rev-diff').className = revDiff >= 0 ? 'pos-val' : 'neg-val';

    document.getElementById('tbl-barb').innerText = `$0.00 (No Splits!)`;
    document.getElementById('tbl-barb-diff').innerText = `$0.00`;

    let totalOverheadAnnual = (mkt.monthlyLease + mkt.monthlySoftware) * 12.0;
    const overheadLabel = document.getElementById('tbl-overhead-label');
    if (overheadLabel) overheadLabel.innerText = `All-In Suite Lease (${mkt.name.split(',')[0]} Lease: $${mkt.monthlyLease}/mo + Software/Ins)`;
    const overheadVal = document.getElementById('tbl-overhead-val');
    if (overheadVal) overheadVal.innerText = `-$${totalOverheadAnnual.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

    document.getElementById('tbl-ads').innerText = `-$${data.adSpend.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById('tbl-ads-diff').innerText = `-$${data.adSpend.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById('tbl-ads-diff').className = data.adSpend === 0 ? 'neutral' : 'neg-val';

    document.getElementById('tbl-prof').innerHTML = `<strong>$${data.netProfit.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong>`;
    document.getElementById('tbl-prof-diff').innerHTML = `<strong>${diff >= 0 ? "+" : ""}$${diff.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong>`;
    document.getElementById('tbl-prof-diff').className = diff >= 0 ? 'pos-val' : 'neg-val';

    document.getElementById('tbl-clients').innerText = `${data.clients} clients`;
    let clientDiff = data.clients - 180;
    document.getElementById('tbl-clients-diff').innerText = (clientDiff >= 0 ? "+" : "") + `${clientDiff}`;
    document.getElementById('tbl-clients-diff').className = clientDiff >= 0 ? 'pos-val' : 'neg-val';

    updateCharts(data.cumulativeProfits, data.baselineCumulative, data.rollingUtils, mkt.name);
}

function initCharts() {
    const ctx1 = document.getElementById('profitChart').getContext('2d');
    profitChartInstance = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: Array.from({length: 365}, (_, i) => `Day ${i+1}`),
            datasets: [
                {
                    label: "Will's Spendable Take-Home Pay ($)",
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0
                },
                {
                    label: 'Baseline Benchmark ($)',
                    data: [],
                    borderColor: '#ef4444',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.2,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', maxTicksLimit: 12 } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: val => '$' + val.toLocaleString() } }
            }
        }
    });

    const ctx2 = document.getElementById('utilChart').getContext('2d');
    utilChartInstance = new Chart(ctx2, {
        type: 'line',
        data: {
            labels: Array.from({length: 365}, (_, i) => `Day ${i+1}`),
            datasets: [
                {
                    label: "Will's Solo Chair Utilization (%)",
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.15)',
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', maxTicksLimit: 12 } },
                y: { min: 0, max: 100, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: val => val + '%' } }
            }
        }
    });
}

function updateCharts(cumProfits, baseProfits, utils, mktName) {
    if (profitChartInstance) {
        profitChartInstance.data.datasets[0].data = cumProfits;
        profitChartInstance.data.datasets[0].label = `Spendable Take-Home in ${mktName}`;
        profitChartInstance.data.datasets[1].data = baseProfits;
        profitChartInstance.update('none');
    }
    if (utilChartInstance) {
        utilChartInstance.data.datasets[0].data = utils;
        utilChartInstance.update('none');
    }
}

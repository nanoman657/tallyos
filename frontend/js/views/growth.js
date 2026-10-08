// Growth: the sense -> think -> act loop, made visible.
//   SENSE  Google Ads spend/clicks and detected sign-ups (with attribution)
//   THINK  booking-frequency forecast, open-chair gap, client value vs cost per client
//   ACT    campaign decisions with reasons; owner approves / pauses / sets budget
import { api } from "../api.js";
import { chartWithTable, sparkline } from "../charts.js";
import { DOW, busy, dayLabel, esc, hhmm, money, num, parseLocal, pct, sheet, shortDate, sourceChip, statusChip, toast } from "../ui.js";

const ACTION_LABEL = { create: "Create campaign", enable: "Re-enable campaign", scale: "Change budget", reschedule: "Change ad days",
                       pause: "Pause campaign", hold: "No change", upload_conversions: "Report conversions to Google" };

export async function render(el) {
  const [runs, fc, campaigns, summary, signups, health] = await Promise.all([
    api.get("/api/growth/runs?limit=15"), api.get("/api/growth/forecast?days=14"), api.get("/api/growth/campaigns"),
    api.get("/api/growth/signups/summary"), api.get("/api/growth/signups?days=28"), api.get("/api/health"),
  ]);
  const last = runs[0];
  const t = last?.think;
  const spend28 = campaigns.reduce((s, c) => s + c.cost, 0);
  const clicks28 = campaigns.reduce((s, c) => s + c.clicks, 0);

  el.innerHTML = `
    <div class="page-head">
      <div><h1>Growth loop</h1><div class="sub">${last ? `Last run ${dayLabel(last.as_of)}` : "Not run yet"} · ${health.ads_backend === "google" ? "Google Ads (live)" : "Google Ads (simulated)"}</div></div>
      <div class="btn-row"><button class="btn small" id="dry">Preview</button><button class="btn small primary" id="run">Run now</button></div>
    </div>

    <section class="card">
      <div class="loop">
        <div class="stage"><div class="k">1 · Sense</div><div class="v">${summary.google_ads_signups} ad sign-ups</div>
          <div class="d">${money(spend28)} spend · ${num(clicks28)} clicks · 28 days</div></div>
        <div class="stage"><div class="k">2 · Think</div><div class="v">${t ? num(t.gap.gap_slots_next_7_days, 1) : "–"} open slots</div>
          <div class="d">next 7 days · ${t ? `${money(t.plan.blended_cpa)}/client vs ${money(t.economics.max_cpa)} max` : ""}</div></div>
        <div class="stage"><div class="k">3 · Act</div><div class="v">${t ? money(t.plan.required_daily_budget) : "–"}/day</div>
          <div class="d">${t ? `budget the gap justifies${t.plan.exploring ? " · exploring" : ""}` : ""}</div></div>
      </div>
      ${last ? decisionsHtml(last) : `<div class="empty">Run the loop to get your first forecast and ad plan.</div>`}
    </section>

    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h2>Booking forecast</h2><span class="small muted">14 days</span></div>
        <div id="fc"></div>
        ${fc.backtest.mae != null ? `<p class="small muted" style="margin:10px 0 0">Accuracy: off by about <b>${num(fc.backtest.mae, 1)}</b> bookings a day over the last two weeks
          (same-day-last-week guess: ${num(fc.backtest.naive_mae, 1)}). Clients rebook every ~${num(fc.shop_mean_interval)} days.</p>` : ""}
        <details><summary>Who's due to rebook</summary>
          <ul class="list">${fc.clients.filter((c) => c.status !== "booked").slice(0, 10).map((c) => `<li><div class="grow"><div class="title">${esc(c.name)}</div>
            <div class="meta">every ~${c.mean_interval} days · last ${shortDate(c.last_visit)}</div></div>
            <span class="small num">${pct(c.p_within_horizon)}</span>${statusChip(c.status)}</li>`).join("")}</ul></details>
      </section>

      <section class="card">
        <div class="card-head"><h2>Sign-up detection</h2><span class="small muted">28 days</span></div>
        <div class="kpis" style="grid-template-columns:repeat(2,1fr)">
          <div class="kpi"><div class="label">From Google Ads</div><div class="value">${summary.google_ads_signups}</div><div class="hint">${summary.google_ads_booked} booked a cut</div></div>
          <div class="kpi"><div class="label">Organic</div><div class="value">${summary.organic_signups}</div><div class="hint">${summary.organic_booked} booked a cut</div></div>
        </div>
        <div id="su"></div>
        <p class="small muted" style="margin:10px 0 0">${liftText(summary)}</p>
        <details><summary>Recent sign-ups</summary>
          <ul class="list">${signups.slice(0, 15).map((s) => `<li><div class="grow"><div class="title">${esc(s.name)}</div>
            <div class="meta">${shortDate(s.at)} ${hhmm(s.at)}${s.campaign_name ? ` · ${esc(s.campaign_name)}` : ""}${s.first_appointment_at ? ` · booked ${shortDate(s.first_appointment_at)}` : " · not booked yet"}</div></div>
            ${sourceChip(s.attribution)}</li>`).join("") || `<li class="muted">No sign-ups yet</li>`}</ul></details>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>Campaigns</h2><span class="small muted">guardrail ${t ? money(t.plan.max_total_daily_budget) : ""}/day total</span></div>
      ${campaigns.length ? `<ul class="list">${campaigns.map(campaignRow).join("")}</ul>` : `<div class="empty">No campaigns yet - the loop creates one when the forecast shows open chairs.</div>`}
    </section>

    <div class="grid-2">
      <section class="card">
        <h2>What a new client is worth</h2>
        ${t ? `
        <div class="stat-row"><span>Average ticket</span><b>${money(t.economics.avg_ticket, 2)}</b></div>
        <div class="stat-row"><span>Margin per visit</span><b>${money(t.economics.margin_per_visit, 2)}</b></div>
        <div class="stat-row"><span>New clients who come back</span><b>${pct(t.economics.new_client_return_rate)}</b></div>
        <div class="stat-row"><span>Expected visits in 12 months</span><b>${num(t.economics.expected_visits, 1)}</b></div>
        <div class="stat-row"><span>12-month client value</span><b>${money(t.economics.ltv)}</b></div>
        <div class="stat-row"><span>Most we'll pay per new client</span><b>${money(t.economics.max_cpa)}</b></div>
        <div class="stat-row"><span>Current cost per booked client</span><b>${money(t.plan.blended_cpa)}</b></div>` : `<div class="empty">Run the loop first.</div>`}
      </section>
      <section class="card">
        <h2>Loop history</h2>
        <ul class="list">${runs.map((r) => `<li><button class="row" data-run="${r.id}"><div class="grow">
          <div class="title">${dayLabel(r.as_of)}${r.dry_run ? " · preview" : ""}</div>
          <div class="meta">${esc((r.think.decisions || []).map((d) => ACTION_LABEL[d.action] || d.action).join(", "))}</div></div>
          <span class="small muted num">${num(r.think.gap?.gap_slots_next_7_days, 1)} open</span></button></li>`).join("")}</ul>
      </section>
    </div>`;

  chartWithTable(el.querySelector("#fc"), {
    rows: fc.days.filter((d) => d.capacity_slots > 0).map((d) => ({
      label: DOW[d.weekday], sub: String(parseLocal(d.date).getDate()),
      values: { booked: d.already_booked, regulars: Math.max(0, d.expected_bookings - d.already_booked - d.organic_new), organic: d.organic_new },
      target: d.capacity_slots * 0.85,
      extra: [["Expected total", num(d.expected_bookings, 1)], ["Open slots", num(Math.max(0, d.capacity_slots * 0.85 - d.expected_bookings), 1)]],
    })),
    series: [
      { key: "booked", label: "Booked", color: "--series-1" },
      { key: "regulars", label: "Regulars due", color: "--series-2" },
      { key: "organic", label: "New (organic)", color: "--series-3" },
    ],
    targetLabel: "Target (85% full)",
  });

  const days = summary.daily.slice(-28);
  chartWithTable(el.querySelector("#su"), {
    rows: days.map((d) => ({
      label: String(parseLocal(d.date).getDate()), sub: DOW[(parseLocal(d.date).getDay() + 6) % 7][0],
      values: { ads: d.ad_signups, organic: d.signups - d.ad_signups },
      extra: [["Ad spend", money(d.ad_cost, 2)]],
    })),
    series: [{ key: "ads", label: "Google Ads", color: "--series-1" }, { key: "organic", label: "Organic", color: "--series-2" }],
    height: 150, valueFmt: (v) => String(v),
  });

  const after = (msg) => { toast(msg); window.dispatchEvent(new Event("tallyos:refresh")); };
  const run = el.querySelector("#run"), dry = el.querySelector("#dry");
  run.addEventListener("click", busy(run, async () => {
    const r = await api.post("/api/growth/run");
    after(`Loop ran: ${r.think.decisions.map((d) => ACTION_LABEL[d.action]).join(", ")}`);
  }));
  dry.addEventListener("click", busy(dry, async () => {
    const r = await api.post("/api/growth/run?dry_run=true");
    showRun({ as_of: new Date().toISOString().slice(0, 10), dry_run: true, think: r.think, act: r.act });
  }));
  el.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => showRun(runs.find((r) => r.id === +b.dataset.run))));
  el.querySelectorAll("[data-camp]").forEach((b) => b.addEventListener("click", () => campaignSheet(campaigns.find((c) => c.id === +b.dataset.camp), after)));
}

function decisionsHtml(run) {
  const acts = run.act || [];
  return (run.think.decisions || []).map((d) => {
    const a = acts.find((x) => x.action === d.action && x.campaign_id === d.campaign_id) || {};
    return `<div class="decision"><div class="what">${esc(ACTION_LABEL[d.action] || d.action)}${d.daily_budget ? ` · ${money(d.daily_budget)}/day` : ""}
      ${d.target_weekdays ? ` · ${d.target_weekdays.map((w) => DOW[w]).join(", ")}` : ""}</div>
      <div class="why">${esc(d.reason)}${a.note ? ` <b>(${esc(a.note)})</b>` : ""}${a.error ? ` <b style="color:var(--critical)">Error: ${esc(a.error)}</b>` : ""}</div></div>`;
  }).join("");
}

function liftText(s) {
  if (s.incremental_signups_per_ad_day != null) {
    return `Days with ads averaged ${num(s.avg_daily_signups_with_ads, 2)} sign-ups vs ${num(s.avg_daily_signups_without_ads, 2)} without ads
      (~${num(s.incremental_signups_per_ad_day, 2)} extra per ad day). Ads run on the quieter weekdays, so treat this as a rough read.`;
  }
  return "Sign-ups are matched to campaigns by Google's click id (gclid), falling back to UTM tags.";
}

function campaignRow(c) {
  return `<li><button class="row" data-camp="${c.id}"><div class="grow">
    <div class="title">${esc(c.name)}</div>
    <div class="meta">${money(c.daily_budget)}/day · ${c.target_weekdays.length ? c.target_weekdays.map((w) => DOW[w]).join(" ") : "every day"}
      · ${num(c.clicks)} clicks · ${c.signups} sign-ups · ${c.booked} booked${c.cpa ? ` · ${money(c.cpa)}/client` : ""}${c.managed_by_loop ? "" : " · manual"}</div></div>
    ${sparkline(c.daily.map((d) => d.clicks), { width: 72, height: 28 })}
    ${statusChip(c.status)}</button></li>`;
}

function campaignSheet(c, after) {
  const pausedForApproval = c.status === "PAUSED" && c.managed_by_loop;
  sheet(c.name, `
    <div class="stat-row"><span>Status</span>${statusChip(c.status)}</div>
    <div class="stat-row"><span>Ad days</span><b>${c.target_weekdays.map((w) => DOW[w]).join(", ") || "Every day"}</b></div>
    <div class="stat-row"><span>Spend · clicks (28d)</span><b>${money(c.cost, 2)} · ${num(c.clicks)}</b></div>
    <div class="stat-row"><span>Sign-ups · booked</span><b>${c.signups} · ${c.booked}</b></div>
    <div class="stat-row"><span>Cost per booked client</span><b>${c.cpa ? money(c.cpa, 2) : "–"}</b></div>
    <label class="field" style="margin-top:14px"><span>Daily budget</span><input id="budget" type="number" min="1" step="1" inputmode="decimal" value="${c.daily_budget}"></label>
    <label class="field"><span><input type="checkbox" id="auto" ${c.managed_by_loop ? "checked" : ""} style="width:auto;min-height:0;margin-right:6px">Let the growth loop manage this campaign</span></label>
    <div class="btn-row">
      <button class="btn primary" id="toggle">${c.status === "ENABLED" ? "Pause" : pausedForApproval ? "Approve & start" : "Start"}</button>
      <button class="btn" id="save">Save</button>
    </div>
    <details style="margin-top:12px"><summary>Ad copy</summary>
      <p class="small"><b>Headlines</b><br>${c.headlines.map(esc).join("<br>")}</p>
      <p class="small"><b>Descriptions</b><br>${c.descriptions.map(esc).join("<br>")}</p>
      <p class="small"><b>Keywords</b><br>${c.keywords.map(esc).join(", ")}</p></details>`, (body, close) => {
    const toggle = body.querySelector("#toggle"), save = body.querySelector("#save");
    toggle.addEventListener("click", busy(toggle, async () => {
      const status = c.status === "ENABLED" ? "PAUSED" : "ENABLED";
      await api.patch(`/api/growth/campaigns/${c.id}`, { status });
      close(); after(status === "ENABLED" ? "Campaign is live" : "Campaign paused");
    }));
    save.addEventListener("click", busy(save, async () => {
      await api.patch(`/api/growth/campaigns/${c.id}`, { daily_budget: +body.querySelector("#budget").value, managed_by_loop: body.querySelector("#auto").checked });
      close(); after("Campaign updated");
    }));
  });
}

function showRun(r) {
  const t = r.think;
  sheet(`${r.dry_run ? "Preview" : "Run"} · ${dayLabel(r.as_of)}`, `
    <h3>Decisions</h3>${decisionsHtml(r)}
    <h3 style="margin-top:14px">Why</h3>
    <div class="stat-row"><span>Expected bookings, next 7 days</span><b>${num(t.forecast_summary.expected_next_7, 1)} of ${num(t.forecast_summary.capacity_next_7, 1)} slots</b></div>
    <div class="stat-row"><span>Open slots below target</span><b>${num(t.gap.gap_slots_next_7_days, 1)}</b></div>
    <div class="stat-row"><span>Days with gaps</span><b>${esc(t.gap.gap_weekday_names.join(", ") || "none")}</b></div>
    <div class="stat-row"><span>Cost per booked client</span><b>${money(t.plan.blended_cpa)}${t.plan.exploring ? " (estimate)" : ""}</b></div>
    <div class="stat-row"><span>Ceiling (⅓ of client value)</span><b>${money(t.economics.max_cpa)}</b></div>
    <div class="stat-row"><span>Budget the gap justifies</span><b>${money(t.plan.required_daily_budget)}/day</b></div>
    ${t.backtest?.mae != null ? `<div class="stat-row"><span>Forecast error (bookings/day)</span><b>${num(t.backtest.mae, 2)} vs ${num(t.backtest.naive_mae, 2)} naive</b></div>` : ""}
    ${(r.act || []).some((a) => a.action === "upload_conversions") ? `<div class="stat-row"><span>Conversions reported to Google</span><b>${(r.act.find((a) => a.action === "upload_conversions")).uploaded}</b></div>` : ""}`);
}

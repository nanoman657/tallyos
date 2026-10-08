// More: inventory, finance (P&L + tax waterfall), menu & staff, settings.
import { api } from "../api.js";
import { chartWithTable } from "../charts.js";
import { DOW, busy, esc, isoDate, money, num, pct, sheet, shortDate, toast, today } from "../ui.js";

const SECTIONS = { finance: "Finance", punctuality: "Punctuality", booksy: "Booksy", inventory: "Inventory",
                   menu: "Menu & staff", settings: "Settings" };

export async function render(el, [section = "finance"]) {
  el.innerHTML = `
    <div class="page-head"><h1>${SECTIONS[section] || "More"}</h1></div>
    <div class="seg" role="group" aria-label="Section" style="margin-bottom:14px;display:flex;overflow-x:auto">
      ${Object.entries(SECTIONS).map(([k, v]) => `<button aria-pressed="${k === section}" data-s="${k}">${v}</button>`).join("")}</div>
    <div id="body"></div>`;
  el.querySelectorAll("[data-s]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/more/${b.dataset.s}`; }));
  const body = el.querySelector("#body");
  await ({ inventory, finance, punctuality, booksy, menu, settings }[section] || finance)(body);
}

async function punctuality(el, days = 28) {
  const r = await api.get(`/api/punctuality?days=${days}`);
  el.innerHTML = `
    <div class="seg" role="group" aria-label="Period" style="margin-bottom:12px">
      ${[[28, "4 weeks"], [90, "3 months"], [365, "Year"]].map(([d, l]) => `<button aria-pressed="${d === days}" data-d="${d}">${l}</button>`).join("")}</div>
    <div class="kpis">
      <div class="kpi"><div class="label">On time</div><div class="value">${pct(r.on_time_share)}</div><div class="hint">within ${r.grace_minutes} min · ${r.tracked_arrivals} arrivals</div></div>
      <div class="kpi"><div class="label">Late arrivals</div><div class="value">${r.late_count}</div><div class="hint">avg ${num(r.avg_minutes_late_when_late)} min late</div></div>
      <div class="kpi"><div class="label">Chair time lost</div><div class="value">${num(r.chair_minutes_lost_to_lateness / 60, 1)} h</div><div class="hint">to late arrivals</div></div>
      <div class="kpi"><div class="label">No-shows</div><div class="value">${r.no_shows}</div><div class="hint">${pct(r.no_show_rate, 1)} · ${num(r.chair_minutes_lost_to_no_shows / 60, 1)} h lost</div></div>
    </div>
    <div class="grid-2">
      <section class="card"><h2>Late arrivals by day</h2><div id="wd"></div>
        <p class="small muted" style="margin:8px 0 0">Share of tracked arrivals more than ${r.grace_minutes} minutes after the booked time.</p></section>
      <section class="card"><div class="card-head"><h2>Often late</h2><span class="small muted">last 6 months</span></div>
        ${r.chronic_latecomers.length ? `<ul class="list">${r.chronic_latecomers.map((c) => `<li>
          <div class="grow"><div class="title"><a href="#/clients/${c.id}">${esc(c.name)}</a></div>
          <div class="meta">late ${c.late} of ${c.tracked} visits · usually ${num(c.avg_late)} min</div></div>
          ${c.phone ? `<a class="btn small" href="sms:${esc(c.phone)}?body=${encodeURIComponent("Hey " + c.name.split(" ")[0] + ", quick reminder to arrive a few minutes early for your next cut so we can give you the full time. Thanks!")}">Text</a>` : ""}</li>`).join("")}</ul>`
          : `<div class="empty">Nobody is regularly late. Nice.</div>`}</section>
    </div>
    ${r.tracked_arrivals ? "" : `<p class="muted small">No arrival times yet. Tap <b>Arrived</b> on Today when a client walks in, or import Booksy check-in times.</p>`}`;
  el.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => punctuality(el, +b.dataset.d)));
  const rows = r.late_share_by_weekday.filter((w) => w.tracked);
  if (rows.length) {
    chartWithTable(el.querySelector("#wd"), {
      rows: rows.map((w) => ({ label: DOW[w.weekday], values: { late: (w.late_share || 0) * 100 }, extra: [["Arrivals tracked", String(w.tracked)]] })),
      series: [{ key: "late", label: "Late arrivals", color: "--series-1" }],
      height: 160, legend: false, valueFmt: (v) => `${v.toFixed(0)}%`,
    });
  }
}

async function booksy(el) {
  const s = await api.get("/api/integrations/booksy");
  const hook = `${location.origin}${s.webhook_path}?secret=YOUR_BOOKSY_WEBHOOK_SECRET`;
  el.innerHTML = `<div class="grid-2">
    <section class="card"><h2>Connection</h2>
      <div class="stat-row"><span>Partner API</span><b>${s.api_configured ? "Connected" : "Not configured"}</b></div>
      <div class="stat-row"><span>Webhooks</span><b>${s.webhook_configured ? "Ready" : "Not configured"}</b></div>
      <div class="stat-row"><span>Last sync</span><b>${s.last_sync_at ? `${shortDate(s.last_sync_at)} · ${s.last_sync_summary.created || 0} new, ${s.last_sync_summary.updated || 0} updated` : "–"}</b></div>
      <div class="stat-row"><span>Booksy bookings in TallyOS</span><b>${num(s.booksy_appointments)}</b></div>
      <div class="stat-row"><span>Visits with an arrival time</span><b>${num(s.with_arrival_time)}</b></div>
      <div class="btn-row" style="margin-top:12px"><button class="btn primary" id="sync" ${s.api_configured ? "" : "disabled"}>Sync now</button></div>
      ${s.api_configured ? "" : `<p class="small muted">Booksy's API is partner-only. Ask your Booksy rep for partner API access, then set
        <code>BOOKSY_API_URL</code>, <code>BOOKSY_API_TOKEN</code> and <code>BOOKSY_BUSINESS_ID</code> on the server. Until then, import a CSV export.</p>`}
    </section>
    <section class="card"><h2>Import a Booksy export</h2>
      <p class="small muted">Export your appointments from Booksy Biz as CSV and pick the file. Re-importing the same file updates bookings instead of duplicating them.
        A check-in / arrival time column is used to measure lateness.</p>
      <label class="field"><span>CSV file</span><input type="file" id="csv" accept=".csv,text/csv"></label>
      <div id="import-result"></div>
    </section>
    <section class="card"><h2>Live updates (webhooks)</h2>
      <p class="small muted">When Booksy enables webhooks for your account, give them this URL so new, changed and cancelled bookings arrive instantly:</p>
      <input readonly value="${esc(hook)}" aria-label="Webhook URL" onclick="this.select()">
      <p class="small muted">Set the same secret as <code>BOOKSY_WEBHOOK_SECRET</code> on the server. Calls without it are refused.</p>
    </section>
    <section class="card"><h2>Recent activity</h2>
      ${s.recent_events.length ? `<ul class="list">${s.recent_events.map((e) => `<li><div class="grow">
        <div class="title">${esc(e.kind.replace("_", " "))} · ${esc(e.action || "")}</div>
        <div class="meta">${shortDate(e.received_at)} · ${esc(e.external_id || "")}${e.error ? ` · ${esc(e.error)}` : ""}</div></div>
        <span class="chip ${e.result === "error" ? "bad" : e.result === "created" ? "good" : ""}">${esc(e.result || "")}</span></li>`).join("")}</ul>`
        : `<div class="empty">Nothing received from Booksy yet.</div>`}
    </section></div>`;
  const sync = el.querySelector("#sync");
  sync.addEventListener("click", busy(sync, async () => {
    const r = await api.post("/api/integrations/booksy/sync");
    toast(`Booksy: ${r.created} new, ${r.updated} updated${r.error ? `, ${r.error} errors` : ""}`);
    booksy(el);
  }));
  el.querySelector("#csv").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const out = el.querySelector("#import-result");
    out.innerHTML = `<p class="muted small">Importing ${esc(file.name)}…</p>`;
    try {
      const r = await api.postText("/api/integrations/booksy/import", await file.text());
      out.innerHTML = `
        <div class="stat-row"><span>Rows read</span><b>${r.rows}</b></div>
        <div class="stat-row"><span>New · updated · unchanged</span><b>${r.created} · ${r.updated} · ${r.unchanged}</b></div>
        <div class="stat-row"><span>Rows with problems</span><b>${r.error}</b></div>
        <details><summary>Columns matched</summary><p class="small">${Object.entries(r.columns).map(([k, v]) => `${esc(k)} ← “${esc(v)}”`).join("<br>")}</p></details>
        ${r.errors.length ? `<details open><summary>Problems</summary><p class="small">${r.errors.map((x) => `Row ${x.row}: ${esc(x.error)}`).join("<br>")}</p></details>` : ""}`;
      toast(r.created + r.updated ? `Booksy: ${r.created} new, ${r.updated} updated` : "Already up to date with this file");
    } catch (err) {
      out.innerHTML = `<p class="small" style="color:var(--critical)">${esc(err.message)}</p>`;
    }
  });
}

async function inventory(el) {
  const products = await api.get("/api/products");
  el.innerHTML = `<section class="card"><ul class="list">${products.map((p) => `<li>
      <div class="grow"><div class="title">${esc(p.name)} ${p.low ? `<span class="chip warn">low</span>` : ""}</div>
        <div class="meta">${esc(p.sku)} · cost ${money(p.unit_cost, 2)}${p.retail_price != null ? ` · sells ${money(p.retail_price, 2)}` : " · back-bar"}</div></div>
      <div class="btn-row" style="align-items:center">
        <button class="btn small" data-d="-1" data-p="${p.id}" aria-label="Use one ${esc(p.name)}">−</button>
        <b class="num" style="min-width:28px;text-align:center">${p.on_hand}</b>
        <button class="btn small" data-d="${p.reorder_qty || 1}" data-p="${p.id}" aria-label="Receive ${p.reorder_qty || 1}">+${p.reorder_qty || 1}</button></div></li>`).join("")}</ul></section>
    <button class="btn" id="add">Add product</button>`;
  el.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", busy(b, async () => {
    const delta = +b.dataset.d;
    await api.post(`/api/products/${b.dataset.p}/stock`, { delta, reason: delta > 0 ? "purchase" : "usage" });
    inventory(el);
  })));
  el.querySelector("#add").addEventListener("click", () => sheet("New product", `
    <label class="field"><span>SKU</span><input id="sku"></label>
    <label class="field"><span>Name</span><input id="name"></label>
    <label class="field"><span>Unit cost</span><input id="cost" type="number" step="0.01" inputmode="decimal"></label>
    <label class="field"><span>Retail price (blank = back-bar supply)</span><input id="retail" type="number" step="0.01" inputmode="decimal"></label>
    <label class="field"><span>On hand · reorder at · reorder qty</span>
      <div class="btn-row" style="flex-wrap:nowrap"><input id="oh" type="number" value="0"><input id="rp" type="number" value="2"><input id="rq" type="number" value="6"></div></label>
    <button class="btn primary" style="width:100%" id="save">Save</button>`, (body, close) => {
    const save = body.querySelector("#save");
    save.addEventListener("click", busy(save, async () => {
      const v = (id) => body.querySelector(`#${id}`).value;
      await api.post("/api/products", { sku: v("sku"), name: v("name"), unit_cost: +v("cost"), retail_price: v("retail") ? +v("retail") : null,
        on_hand: +v("oh"), reorder_point: +v("rp"), reorder_qty: +v("rq") });
      close(); toast("Product added"); inventory(el);
    }));
  }));
}

async function finance(el, period = "month") {
  const t = today();
  const ranges = {
    // Month to date: prorating a full month of rent against a partial month of sales would show a fake loss.
    month: [new Date(t.getFullYear(), t.getMonth(), 1), new Date(t.getFullYear(), t.getMonth(), t.getDate() + 1)],
    last: [new Date(t.getFullYear(), t.getMonth() - 1, 1), new Date(t.getFullYear(), t.getMonth(), 1)],
    ytd: [new Date(t.getFullYear(), 0, 1), new Date(t.getFullYear(), t.getMonth(), t.getDate() + 1)],
  };
  const [s, e] = ranges[period];
  const f = await api.get(`/api/finance/summary?start=${isoDate(s)}&end=${isoDate(e)}`);
  const cost = (v) => (v > 0.005 ? "−" + money(v, 2) : money(0, 2));
  const row = (k, v, strong) => `<div class="stat-row"><span>${k}</span><b ${strong ? 'style="font-weight:700"' : ""}>${v}</b></div>`;
  el.innerHTML = `
    <div class="seg" role="group" aria-label="Period" style="margin-bottom:12px">
      ${[["month", "Month to date"], ["last", "Last month"], ["ytd", "Year to date"]].map(([k, v]) => `<button aria-pressed="${k === period}" data-p="${k}">${v}</button>`).join("")}</div>
    <div class="kpis">
      <div class="kpi"><div class="label">Revenue</div><div class="value">${money(f.revenue)}</div><div class="hint">${f.tickets} tickets</div></div>
      <div class="kpi"><div class="label">Operating profit</div><div class="value">${money(f.operating_profit)}</div><div class="hint">before tax</div></div>
      <div class="kpi"><div class="label">Average ticket</div><div class="value">${money(f.avg_ticket, 2)}</div><div class="hint">services + retail</div></div>
      <div class="kpi"><div class="label">Ad spend</div><div class="value">${money(f.ad_spend)}</div><div class="hint">Google Ads</div></div>
    </div>
    <div class="grid-2">
      <section class="card"><h2>Profit &amp; loss</h2>
        ${row("Service revenue", money(f.service_revenue, 2))}
        ${row("Retail revenue", money(f.product_revenue, 2))}
        ${row("Card fees", cost(f.card_fees))}
        ${row("Supplies used (COGS)", cost(f.cogs))}
        ${row("Barber commissions", cost(f.commissions))}
        ${row("Gross profit", money(f.gross_profit, 2), true)}
        ${row("Rent &amp; software", cost(f.rent_and_software))}
        ${row("Google Ads", cost(f.ad_spend))}
        ${f.other_expenses.map((x) => row(esc(x.category[0].toUpperCase() + x.category.slice(1)), cost(x.amount))).join("")}
        ${row("Operating profit", money(f.operating_profit, 2), true)}
        <p class="small muted">Tips (${money(f.tips, 2)}) pass through to the barber and aren't counted as revenue.</p></section>
      <section class="card"><h2>Taxes &amp; take-home</h2>
        ${row("Self-employment tax", cost(f.taxes.se_tax))}
        ${row("Federal income tax", cost(f.taxes.federal_income_tax))}
        ${row("State / city tax", cost(f.taxes.state_city_tax))}
        ${row("Health insurance", cost(f.taxes.health_insurance_annual))}
        ${row("Take-home for the period", money(f.taxes.true_take_home, 2), true)}
        <p class="small muted">Estimated from this period's profit annualized to ${money(f.annualized_take_home)}/yr take-home (2024 brackets, QBI deduction). Not tax advice.</p></section>
    </div>`;
  el.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => finance(el, b.dataset.p)));
}

async function menu(el) {
  const [services, staff] = await Promise.all([api.get("/api/services"), api.get("/api/staff")]);
  el.innerHTML = `<div class="grid-2">
    <section class="card"><div class="card-head"><h2>Services</h2><button class="btn small" id="add-svc">Add</button></div>
      <ul class="list">${services.map((s) => `<li><button class="row" data-svc="${s.id}"><div class="grow"><div class="title">${esc(s.name)}${s.active ? "" : " (hidden)"}</div>
        <div class="meta">${s.duration_min} min · supplies ${money(s.cogs, 2)}</div></div><b class="num">${money(s.price)}</b></button></li>`).join("")}</ul></section>
    <section class="card"><div class="card-head"><h2>Staff</h2><button class="btn small" id="add-staff">Add</button></div>
      <ul class="list">${staff.map((s) => `<li><button class="row" data-staff="${s.id}"><div class="grow"><div class="title">${esc(s.name)}${s.active ? "" : " (inactive)"}</div>
        <div class="meta">${esc(s.role)}${s.commission_rate ? ` · ${pct(s.commission_rate)} commission` : ""}</div></div></button></li>`).join("")}</ul></section></div>`;
  const svcForm = (s = { name: "", price: "", duration_min: 40, cogs: 0, active: true }) => sheet(s.id ? "Edit service" : "New service", `
    <label class="field"><span>Name</span><input id="name" value="${esc(s.name)}"></label>
    <label class="field"><span>Price</span><input id="price" type="number" step="1" value="${s.price}"></label>
    <label class="field"><span>Minutes (incl. cleanup)</span><input id="dur" type="number" value="${s.duration_min}"></label>
    <label class="field"><span>Supplies cost per service</span><input id="cogs" type="number" step="0.01" value="${s.cogs}"></label>
    <label class="field"><span><input type="checkbox" id="active" ${s.active ? "checked" : ""} style="width:auto;min-height:0;margin-right:6px">Bookable</span></label>
    <button class="btn primary" style="width:100%" id="save">Save</button>`, (body, close) => {
    const save = body.querySelector("#save");
    save.addEventListener("click", busy(save, async () => {
      const v = (id) => body.querySelector(`#${id}`).value;
      const payload = { name: v("name"), price: +v("price"), duration_min: +v("dur"), cogs: +v("cogs"), active: body.querySelector("#active").checked };
      await (s.id ? api.put(`/api/services/${s.id}`, payload) : api.post("/api/services", payload));
      close(); toast("Saved"); menu(el);
    }));
  });
  const staffForm = (s = { name: "", role: "barber", commission_rate: 0, active: true }) => sheet(s.id ? "Edit staff" : "New staff", `
    <label class="field"><span>Name</span><input id="name" value="${esc(s.name)}"></label>
    <label class="field"><span>Role</span><select id="role"><option ${s.role === "barber" ? "selected" : ""}>barber</option><option ${s.role === "admin" ? "selected" : ""}>admin</option></select></label>
    <label class="field"><span>Commission on services (0-1)</span><input id="comm" type="number" step="0.05" min="0" max="1" value="${s.commission_rate}"></label>
    <label class="field"><span><input type="checkbox" id="active" ${s.active ? "checked" : ""} style="width:auto;min-height:0;margin-right:6px">Active (counts toward chair capacity)</span></label>
    <button class="btn primary" style="width:100%" id="save">Save</button>`, (body, close) => {
    const save = body.querySelector("#save");
    save.addEventListener("click", busy(save, async () => {
      const v = (id) => body.querySelector(`#${id}`).value;
      const payload = { name: v("name"), role: v("role"), commission_rate: +v("comm"), active: body.querySelector("#active").checked };
      await (s.id ? api.put(`/api/staff/${s.id}`, payload) : api.post("/api/staff", payload));
      close(); toast("Saved"); menu(el);
    }));
  });
  el.querySelector("#add-svc").addEventListener("click", () => svcForm());
  el.querySelector("#add-staff").addEventListener("click", () => staffForm());
  el.querySelectorAll("[data-svc]").forEach((b) => b.addEventListener("click", () => svcForm(services.find((s) => s.id === +b.dataset.svc))));
  el.querySelectorAll("[data-staff]").forEach((b) => b.addEventListener("click", () => staffForm(staff.find((s) => s.id === +b.dataset.staff))));
}

async function settings(el) {
  const [shop, health] = await Promise.all([api.get("/api/shop"), api.get("/api/health")]);
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const toMin = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
  let theme = "system";
  try { theme = localStorage.getItem("tallyos-theme") || "system"; } catch { /* ignore */ }
  el.innerHTML = `<div class="grid-2">
    <section class="card"><h2>Shop</h2>
      <label class="field"><span>Name</span><input id="name" value="${esc(shop.name)}"></label>
      <label class="field"><span>Address</span><input id="address" value="${esc(shop.address)}"></label>
      <label class="field"><span>Open days</span><div class="seg" id="days" style="display:flex;flex-wrap:wrap">${DOW.map((d, i) => `<button type="button" data-w="${i}" aria-pressed="${shop.open_weekdays.includes(i)}">${d}</button>`).join("")}</div></label>
      <div class="btn-row" style="flex-wrap:nowrap">
        <label class="field" style="flex:1"><span>Opens</span><input id="open" type="time" value="${hm(shop.open_minute)}"></label>
        <label class="field" style="flex:1"><span>Closes</span><input id="close" type="time" value="${hm(shop.close_minute)}"></label>
        <label class="field" style="flex:1"><span>Break (min)</span><input id="brk" type="number" value="${shop.break_minutes}"></label></div>
      <div class="btn-row" style="flex-wrap:nowrap">
        <label class="field" style="flex:1"><span>Rent / mo</span><input id="rent" type="number" value="${shop.monthly_rent}"></label>
        <label class="field" style="flex:1"><span>Software / mo</span><input id="soft" type="number" value="${shop.monthly_software}"></label></div>
      <div class="btn-row" style="flex-wrap:nowrap">
        <label class="field" style="flex:1"><span>Card fee rate</span><input id="fee" type="number" step="0.001" value="${shop.card_fee_rate}"></label>
        <label class="field" style="flex:1"><span>State + city tax</span><input id="tax" type="number" step="0.001" value="${shop.state_city_tax_rate}"></label></div>
      <label class="field"><span>Health insurance / yr</span><input id="hi" type="number" value="${shop.health_insurance_annual}"></label>
      <label class="field"><span>Filing status</span><select id="fs"><option value="head_of_household" ${shop.filing_status === "head_of_household" ? "selected" : ""}>Head of household</option><option value="single" ${shop.filing_status === "single" ? "selected" : ""}>Single</option></select></label>
      <button class="btn primary" id="save">Save</button></section>
    <section class="card"><h2>App</h2>
      <label class="field"><span>Theme</span><div class="seg" id="theme">${["system", "light", "dark"].map((t) => `<button type="button" data-t="${t}" aria-pressed="${t === theme}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></label>
      <div class="stat-row"><span>Google Ads connection</span><b>${health.ads_backend === "google" ? "Live account" : "Simulated (demo)"}</b></div>
      <p class="small muted">Connect a real Google Ads account on the server with <code>TALLYOS_ADS_BACKEND=google</code> and your API credentials. New campaigns on a live account wait for your approval in Growth.</p>
      <div class="stat-row"><span>Public sign-up page</span><b><a href="join.html" target="_blank" rel="noopener">join.html</a></b></div>
      <p class="small muted">Point your ads and Instagram bio at this page; it records Google's click id so sign-ups are credited to the right campaign.</p></section></div>`;
  el.querySelectorAll("#days button").forEach((b) => b.addEventListener("click", () => b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"))));
  el.querySelectorAll("#theme button").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("#theme button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const t = b.dataset.t;
    if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
    try { t === "system" ? localStorage.removeItem("tallyos-theme") : localStorage.setItem("tallyos-theme", t); } catch { /* ignore */ }
  }));
  const save = el.querySelector("#save");
  save.addEventListener("click", busy(save, async () => {
    const v = (id) => el.querySelector(`#${id}`).value;
    await api.put("/api/shop", {
      name: v("name"), address: v("address"),
      open_weekdays: [...el.querySelectorAll("#days button[aria-pressed=true]")].map((b) => +b.dataset.w),
      open_minute: toMin(v("open")), close_minute: toMin(v("close")), break_minutes: +v("brk"),
      monthly_rent: +v("rent"), monthly_software: +v("soft"), card_fee_rate: +v("fee"), state_city_tax_rate: +v("tax"),
      health_insurance_annual: +v("hi"), filing_status: v("fs"),
    });
    toast("Shop settings saved");
  }));
}

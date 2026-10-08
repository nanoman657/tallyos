// Today: KPIs, today's chair, checkout, this week's booking forecast, low stock.
import { api } from "../api.js";
import { stackedColumns } from "../charts.js";
import { DOW, busy, dayLabel, esc, hhmm, money, num, parseLocal, sheet, sourceChip, statusChip, toast } from "../ui.js";

export async function render(el) {
  const d = await api.get("/api/dashboard");
  const live = d.appointments.filter((a) => a.status !== "cancelled");
  const done = live.filter((a) => a.status === "completed").length;

  el.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(d.shop)}</h1><div class="sub">${dayLabel(d.today)}${d.open_today ? "" : " · closed today"}</div></div>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="label">Bookings today</div><div class="value">${live.length}</div><div class="hint">${done} checked out</div></div>
      <div class="kpi"><div class="label">Sales today</div><div class="value">${money(d.sales_today.revenue)}</div><div class="hint">+ ${money(d.sales_today.tips)} tips</div></div>
      <div class="kpi"><div class="label">Profit this month</div><div class="value">${money(d.month_to_date.operating_profit)}</div><div class="hint">after rent &amp; ads</div></div>
      <div class="kpi"><div class="label">New sign-ups</div><div class="value">${d.new_signups_7d}</div><div class="hint">last 7 days</div></div>
    </div>
    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h2>Today's chair</h2><a href="#/schedule" class="small">Schedule</a></div>
        ${live.length ? `<ul class="list" id="appts">${live.map(row).join("")}</ul>` : `<div class="empty">No bookings today.</div>`}
      </section>
      <div>
        <section class="card">
          <div class="card-head"><h2>This week</h2><a href="#/growth" class="small">Forecast</a></div>
          <div id="week"></div>
          <p class="small muted" style="margin:8px 0 0">Predicted bookings use each client's own rebooking rhythm. Gaps under the dashed line are what the growth loop advertises to fill.</p>
        </section>
        ${d.low_stock.length ? `<section class="card"><div class="card-head"><h2>Low stock</h2><a href="#/more/inventory" class="small">Inventory</a></div>
          <ul class="list">${d.low_stock.map((p) => `<li><div class="grow"><div class="title">${esc(p.name)}</div><div class="meta">${p.on_hand} on hand · reorder at ${p.reorder_point}</div></div><span class="chip warn">reorder ${p.reorder_qty}</span></li>`).join("")}</ul></section>` : ""}
      </div>
    </div>`;

  stackedColumns(el.querySelector("#week"), {
    rows: d.week_forecast.filter((f) => f.capacity_slots > 0).map((f) => ({
      label: DOW[f.weekday], sub: String(parseLocal(f.date).getDate()),
      values: { booked: f.already_booked, predicted: Math.max(0, f.expected_bookings - f.already_booked) },
      target: f.capacity_slots * 0.85,
      extra: [["Chair capacity", num(f.capacity_slots, 1)]],
    })),
    series: [{ key: "booked", label: "Booked", color: "--series-1" }, { key: "predicted", label: "Predicted", color: "--series-2" }],
    targetLabel: "85% of capacity", height: 170,
  });

  el.querySelectorAll("[data-checkout]").forEach((b) => b.addEventListener("click", () => checkout(live.find((a) => a.id === +b.dataset.checkout))));
  el.querySelectorAll("[data-noshow]").forEach((b) => b.addEventListener("click", busy(b, async () => {
    await api.post(`/api/appointments/${b.dataset.noshow}/status`, { status: "no_show" });
    toast("Marked as no-show");
    window.dispatchEvent(new Event("tallyos:refresh"));
  })));
}

function row(a) {
  const actions = a.status === "booked"
    ? `<div class="btn-row"><button class="btn small primary" data-checkout="${a.id}">Check out</button><button class="btn small ghost" data-noshow="${a.id}" aria-label="No-show">No-show</button></div>`
    : statusChip(a.status);
  return `<li><span class="time">${hhmm(a.start_at)}</span>
    <div class="grow"><div class="title">${esc(a.client_name)}</div><div class="meta">${esc(a.service_name)} · ${money(a.price)} ${a.client_source === "google_ads" ? sourceChip("google_ads") : ""}</div></div>
    ${actions}</li>`;
}

export async function checkout(appt, onDone) {
  const products = (await api.get("/api/products")).filter((p) => p.retail_price != null && p.on_hand > 0);
  sheet(`Check out ${appt.client_name}`, `
    <div class="stat-row"><span>${esc(appt.service_name)}</span><b>${money(appt.price, 2)}</b></div>
    <label class="field" style="margin-top:12px"><span>Add retail product</span>
      <select id="prod"><option value="">None</option>${products.map((p) => `<option value="${p.id}">${esc(p.name)} - ${money(p.retail_price, 2)}</option>`).join("")}</select></label>
    <label class="field"><span>Tip</span>
      <div class="seg" id="tips">${[0, 0.15, 0.2, 0.25].map((t, i) => `<button type="button" data-t="${t}" aria-pressed="${i === 2}">${t ? `${t * 100}%` : "None"}</button>`).join("")}</div></label>
    <label class="field"><span>Payment</span>
      <div class="seg" id="pay"><button type="button" data-p="card" aria-pressed="true">Card</button><button type="button" data-p="cash" aria-pressed="false">Cash</button></div></label>
    <button class="btn primary" style="width:100%" id="go">Complete sale</button>`, (body, close) => {
    const pick = (group) => body.querySelectorAll(`#${group} button`).forEach((b) => b.addEventListener("click", () =>
      body.querySelectorAll(`#${group} button`).forEach((x) => x.setAttribute("aria-pressed", String(x === b)))));
    pick("tips"); pick("pay");
    const go = body.querySelector("#go");
    go.addEventListener("click", busy(go, async () => {
      const tipRate = +body.querySelector("#tips [aria-pressed=true]").dataset.t;
      const pid = body.querySelector("#prod").value;
      const sale = await api.post(`/api/appointments/${appt.id}/checkout`, {
        tip: Math.round(appt.price * tipRate * 100) / 100,
        payment_method: body.querySelector("#pay [aria-pressed=true]").dataset.p,
        products: pid ? [{ product_id: +pid, qty: 1 }] : [],
      });
      close();
      toast(`Paid ${money(sale.subtotal + sale.tip, 2)}`);
      onDone ? onDone() : window.dispatchEvent(new Event("tallyos:refresh"));
    }));
  });
}

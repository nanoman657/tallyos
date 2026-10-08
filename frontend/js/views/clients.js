// Clients: searchable book, client profile with visit history and the forecaster's rebooking outlook.
import { api } from "../api.js";
import { busy, esc, initials, lateChip, money, num, parseLocal, pct, sheet, shortDate, sourceChip, statusChip, toast, today } from "../ui.js";
import { bookSheet } from "./schedule.js";

export async function render(el, [clientId]) {
  el.innerHTML = `
    <div class="page-head"><div><h1>Clients</h1><div class="sub" id="count"></div></div></div>
    <input class="search" id="q" type="search" placeholder="Search name, phone or email" aria-label="Search clients">
    <section class="card"><ul class="list" id="list"></ul></section>
    <button class="fab" aria-label="Add client" id="add">+</button>`;
  const list = el.querySelector("#list");
  let timer;
  const load = async () => {
    const rows = await api.get(`/api/clients?q=${encodeURIComponent(el.querySelector("#q").value)}&limit=200`);
    el.querySelector("#count").textContent = `${rows.length}${rows.length === 200 ? "+" : ""} clients`;
    list.innerHTML = rows.length ? rows.map((c) => `<li><button class="row" data-id="${c.id}">
        <span class="avatar">${initials(c.name)}</span>
        <div class="grow"><div class="title">${esc(c.name)}</div>
          <div class="meta">${c.visits || 0} visits${c.last_visit ? ` · last ${shortDate(c.last_visit)}` : ""}${c.next_at ? ` · next ${shortDate(c.next_at)}` : ""}</div></div>
        ${c.often_late ? `<span class="chip warn"><span class="dot"></span>often late</span>` : ""}
        ${c.source === "google_ads" || c.source === "booksy" ? sourceChip(c.source) : ""}</button></li>`).join("")
      : `<li class="empty">No clients match.</li>`;
    list.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => profile(+b.dataset.id)));
  };
  el.querySelector("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 200); });
  el.querySelector("#add").addEventListener("click", () => addClient(load));
  await load();
  if (clientId) profile(+clientId);
}

async function profile(id) {
  const c = await api.get(`/api/clients/${id}`);
  const o = c.outlook;
  const completed = c.appointments.filter((a) => a.status === "completed");
  const spend = completed.reduce((s, a) => s + a.price, 0);
  sheet(c.name, `
    <div class="btn-row" style="margin-bottom:12px">
      ${c.phone ? `<a class="btn small" href="tel:${esc(c.phone)}">Call</a><a class="btn small" href="sms:${esc(c.phone)}">Text</a>` : ""}
      <button class="btn small primary" id="book">Book</button></div>
    <div class="stat-row"><span>Source</span><span>${sourceChip(c.source)} ${c.campaign_name ? `<span class="small muted">${esc(c.campaign_name)}</span>` : ""}</span></div>
    <div class="stat-row"><span>Client since</span><b>${shortDate(c.created_at)}</b></div>
    <div class="stat-row"><span>Visits · lifetime spend</span><b>${completed.length} · ${money(spend)}</b></div>
    ${o ? `
      <h3 style="margin-top:16px">Rebooking outlook</h3>
      <div class="stat-row"><span>Status</span>${statusChip(o.status)}</div>
      <div class="stat-row"><span>Usual gap between cuts</span><b>${o.mean_interval} days</b></div>
      <div class="stat-row"><span>Next visit expected</span><b>${o.next_booked ? `booked ${shortDate(o.next_booked)}` : o.next_visit_expected ? shortDate(o.next_visit_expected) : "–"}</b></div>
      <div class="stat-row"><span>Chance they book in the next 30 days</span><b>${pct(o.p_within_horizon)}</b></div>
      ${o.status === "overdue" || o.status === "lapsed" ? `<p class="small muted">Overdue clients are good candidates for a personal text before spending on ads.</p>` : ""}` : ""}
    ${punctualityHtml(c.punctuality)}
    <h3 style="margin-top:16px">History</h3>
    <ul class="list">${c.appointments.slice(0, 12).map((a) => `<li><div class="grow"><div class="title">${esc(a.service_name)}</div>
      <div class="meta">${shortDate(a.start_at)} · ${money(a.price)}${a.external_source === "booksy" ? " · Booksy" : ""}</div></div>
      ${lateChip(a.arrived_at ? Math.max(0, Math.round((parseLocal(a.arrived_at) - parseLocal(a.start_at)) / 60000)) : null)}${statusChip(a.status)}</li>`).join("") || `<li class="muted">No visits yet</li>`}</ul>`,
  (body, close) => body.querySelector("#book").addEventListener("click", () => { close(); bookSheet(today(), () => toast("Booked"), c); }));
}

function punctualityHtml(p) {
  if (!p || (!p.tracked_arrivals && !p.no_shows)) return "";
  return `<h3 style="margin-top:16px">Punctuality ${p.chronic ? `<span class="chip warn"><span class="dot"></span>often late</span>` : ""}</h3>
    <div class="stat-row"><span>Late (over ${p.grace_minutes} min)</span><b>${p.late_count} of ${p.tracked_arrivals} visits</b></div>
    ${p.avg_minutes_late_when_late ? `<div class="stat-row"><span>Usually late by</span><b>${num(p.avg_minutes_late_when_late)} min</b></div>` : ""}
    ${p.worst_minutes_late ? `<div class="stat-row"><span>Latest arrival</span><b>${p.worst_minutes_late} min</b></div>` : ""}
    <div class="stat-row"><span>No-shows</span><b>${p.no_shows}${p.no_show_rate != null ? ` (${pct(p.no_show_rate)})` : ""}</b></div>
    ${p.chronic ? `<p class="small muted">Consider booking them into the last slot before a break, or asking them to arrive 10 minutes early.</p>` : ""}`;
}

function addClient(onDone) {
  sheet("New client", `
    <label class="field"><span>Name</span><input id="name" autocomplete="name"></label>
    <label class="field"><span>Phone</span><input id="phone" inputmode="tel" autocomplete="tel"></label>
    <label class="field"><span>Email</span><input id="email" type="email" autocomplete="email"></label>
    <label class="field"><span>How did they find you?</span><select id="src">
      <option value="walk_in">Walk-in</option><option value="referral">Referral</option><option value="organic">Online / social</option></select></label>
    <button class="btn primary" style="width:100%" id="save">Save client</button>`, (body, close) => {
    const save = body.querySelector("#save");
    save.addEventListener("click", busy(save, async () => {
      const name = body.querySelector("#name").value.trim();
      if (!name) throw new Error("Name is required");
      await api.post("/api/clients", { name, phone: body.querySelector("#phone").value.trim() || null,
        email: body.querySelector("#email").value.trim() || null, source: body.querySelector("#src").value });
      close(); toast(`Added ${name}`); onDone();
    }));
  });
}

// Schedule: swipeable day strip, day's appointments, booking sheet with live availability.
import { api } from "../api.js";
import { DOW, LATE_GRACE_MIN, addDays, booksyChip, busy, esc, hhmm, isoDate, lateChip, money, parseLocal, sheet, sourceChip, statusChip, toast, today, weekdayIdx } from "../ui.js";
import { checkout } from "./today.js";

let selected = null;

export async function render(el) {
  const shop = await api.get("/api/shop");
  selected = selected || today();
  const start = addDays(today(), -3);
  const days = Array.from({ length: 24 }, (_, i) => addDays(start, i));

  el.innerHTML = `
    <div class="page-head"><div><h1>Schedule</h1><div class="sub" id="day-title"></div></div></div>
    <div class="day-strip" role="group" aria-label="Pick a day">
      ${days.map((d) => `<button data-d="${isoDate(d)}" class="${shop.open_weekdays.includes(weekdayIdx(d)) ? "" : "closed"}"
        aria-pressed="${isoDate(d) === isoDate(selected)}"><span class="dow">${DOW[weekdayIdx(d)]}</span><span class="dom">${d.getDate()}</span></button>`).join("")}
    </div>
    <section class="card" id="day"></section>
    <button class="fab" aria-label="New booking" id="new">+</button>`;

  const strip = el.querySelector(".day-strip");
  strip.querySelector("[aria-pressed=true]")?.scrollIntoView({ inline: "center", block: "nearest" });
  strip.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    selected = new Date(b.dataset.d + "T00:00");
    strip.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    loadDay(el, shop);
  });
  el.querySelector("#new").addEventListener("click", () => bookSheet(selected, () => loadDay(el, shop)));
  await loadDay(el, shop);
}

async function loadDay(el, shop) {
  const box = el.querySelector("#day");
  const appts = await api.get(`/api/appointments?start=${isoDate(selected)}`);
  if (!box?.isConnected) return;   // user navigated away while loading
  el.querySelector("#day-title").textContent = selected.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const open = shop.open_weekdays.includes(weekdayIdx(selected));
  const minutes = appts.filter((a) => a.status !== "cancelled").reduce((s, a) => s + a.duration_min, 0);
  const cap = open ? shop.close_minute - shop.open_minute - shop.break_minutes : 0;
  box.innerHTML = `
    <div class="card-head"><h2>${appts.length} appointment${appts.length === 1 ? "" : "s"}</h2>
      <span class="small muted">${open ? `${Math.round((minutes / Math.max(cap, 1)) * 100)}% of chair time booked` : "Closed"}</span></div>
    ${appts.length ? `<ul class="list">${appts.map((a) => `<li><button class="row" data-id="${a.id}">
        <span class="time">${hhmm(a.start_at)}</span>
        <div class="grow"><div class="title">${esc(a.client_name)}</div><div class="meta">${esc(a.service_name)} · ${a.duration_min} min · ${esc(a.staff_name)} ${booksyChip(a)} ${a.client_source === "google_ads" ? sourceChip("google_ads") : ""}</div></div>
        ${lateChip(a.minutes_late)} ${statusChip(a.status)}</button></li>`).join("")}</ul>`
      : `<div class="empty">${open ? "Nothing booked yet. Tap + to add a booking." : "The shop is closed this day."}</div>`}`;
  box.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => apptActions(appts.find((a) => a.id === +b.dataset.id), () => loadDay(el, shop))));
}

function apptActions(a, refresh) {
  const live = a.status === "booked";
  sheet(a.client_name, `
    <div class="stat-row"><span>When</span><b>${parseLocal(a.start_at).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}</b></div>
    <div class="stat-row"><span>Service</span><b>${esc(a.service_name)} · ${money(a.price)}</b></div>
    <div class="stat-row"><span>Barber</span><b>${esc(a.staff_name)}</b></div>
    <div class="stat-row"><span>Phone</span><b>${a.client_phone ? `<a href="tel:${esc(a.client_phone)}">${esc(a.client_phone)}</a>` : "–"}</b></div>
    <div class="stat-row"><span>Status</span>${statusChip(a.status)}</div>
    <div class="stat-row"><span>Arrived</span><span>${a.arrived_at ? `${hhmm(a.arrived_at)} ${lateChip(a.minutes_late)}` : "–"}</span></div>
    ${a.external_source === "booksy" ? `<div class="stat-row"><span>Booked via</span><b>Booksy</b></div>` : ""}
    ${live ? `<div class="btn-row" style="margin-top:16px">
      ${a.arrived_at ? "" : `<button class="btn" id="arr">Arrived</button>`}
      <button class="btn primary" id="co">Check out</button>
      <button class="btn" data-s="no_show">No-show</button>
      <button class="btn danger" data-s="cancelled">Cancel</button></div>` : ""}
    <p style="margin-top:14px"><a href="#/clients/${a.client_id}">Open client profile</a></p>`, (body, close) => {
    body.querySelector("#co")?.addEventListener("click", () => { close(); checkout(a, refresh); });
    const arr = body.querySelector("#arr");
    arr?.addEventListener("click", busy(arr, async () => {
      const r = await api.post(`/api/appointments/${a.id}/checkin`, {});
      close(); toast(r.minutes_late > LATE_GRACE_MIN ? `Checked in - ${r.minutes_late} min late` : "Checked in - on time"); refresh();
    }));
    body.querySelectorAll("[data-s]").forEach((b) => b.addEventListener("click", busy(b, async () => {
      await api.post(`/api/appointments/${a.id}/status`, { status: b.dataset.s });
      close(); toast(b.dataset.s === "cancelled" ? "Booking cancelled" : "Marked as no-show"); refresh();
    })));
  });
}

export async function bookSheet(day, onDone, presetClient) {
  const services = await api.get("/api/services");
  const active = services.filter((s) => s.active);
  sheet("New booking", `
    <label class="field"><span>Client</span>
      <input id="q" placeholder="Search name or phone" autocomplete="off" value="${esc(presetClient?.name || "")}"></label>
    <ul class="list" id="matches" style="margin:-6px 0 8px"></ul>
    <div id="newclient" hidden>
      <label class="field"><span>New client phone</span><input id="phone" inputmode="tel" placeholder="(713) 555-0100"></label>
    </div>
    <label class="field"><span>Service</span><select id="svc">${active.map((s) => `<option value="${s.id}">${esc(s.name)} · ${s.duration_min} min · ${money(s.price)}</option>`).join("")}</select></label>
    <label class="field"><span>Day</span><input type="date" id="day" value="${isoDate(day)}"></label>
    <div class="slots" id="slots"></div>
    <button class="btn primary" style="width:100%;margin-top:14px" id="book" disabled>Book</button>`, (body, close) => {
    let client = presetClient || null, slot = null, timer;
    const q = body.querySelector("#q"), matches = body.querySelector("#matches"), book = body.querySelector("#book");
    const ready = () => { book.disabled = !(slot && (client || q.value.trim().length > 1)); };
    q.addEventListener("input", () => {
      client = null; ready();
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const term = q.value.trim();
        if (term.length < 2) { matches.innerHTML = ""; body.querySelector("#newclient").hidden = true; return; }
        const rows = await api.get(`/api/clients?q=${encodeURIComponent(term)}&limit=5`);
        matches.innerHTML = rows.map((c) => `<li><button class="row" data-c="${c.id}"><div class="grow"><div class="title">${esc(c.name)}</div><div class="meta">${esc(c.phone || "")}</div></div></button></li>`).join("");
        body.querySelector("#newclient").hidden = false;
        matches.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => {
          client = rows.find((c) => c.id === +b.dataset.c); q.value = client.name; matches.innerHTML = "";
          body.querySelector("#newclient").hidden = true; ready();
        }));
      }, 200);
    });
    const loadSlots = async () => {
      slot = null; ready();
      const box = body.querySelector("#slots");
      const rows = await api.get(`/api/availability?day=${body.querySelector("#day").value}&service_id=${body.querySelector("#svc").value}`);
      box.innerHTML = rows.length ? rows.map((s, i) => `<button type="button" data-i="${i}" aria-pressed="false">${hhmm(s.start_at)}</button>`).join("")
        : `<div class="muted small">No open times that day.</div>`;
      box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        slot = rows[+b.dataset.i];
        box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); ready();
      }));
    };
    body.querySelector("#svc").addEventListener("change", loadSlots);
    body.querySelector("#day").addEventListener("change", loadSlots);
    loadSlots();
    book.addEventListener("click", busy(book, async () => {
      if (!client) {
        client = await api.post("/api/clients", { name: q.value.trim(), phone: body.querySelector("#phone").value.trim() || null, source: "walk_in" });
      }
      await api.post("/api/appointments", { client_id: client.id, service_id: +body.querySelector("#svc").value, start_at: slot.start_at, staff_id: slot.staff_id });
      close(); toast(`Booked ${client.name} at ${hhmm(slot.start_at)}`); onDone?.();
    }));
  });
}

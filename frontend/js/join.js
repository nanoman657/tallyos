// Public sign-up + first booking page: the landing page Google Ads points to.
// It captures the gclid (Google auto-tagging) and UTM tags from the URL so the
// backend can credit the sign-up to the campaign that produced it -- this is
// the DETECT half of the growth loop.
import { api } from "./api.js";
import { addDays, esc, hhmm, isoDate, money, parseLocal, toast, today } from "./ui.js";

const KEY = "tallyos-attribution";
const params = new URLSearchParams(location.search);
const fromUrl = Object.fromEntries(["gclid", "utm_source", "utm_medium", "utm_campaign"]
  .filter((k) => params.get(k)).map((k) => [k, params.get(k)]));

// Keep tracking ids if the visitor reloads or comes back later the same session.
let attribution = fromUrl;
try {
  if (Object.keys(fromUrl).length) sessionStorage.setItem(KEY, JSON.stringify(fromUrl));
  else attribution = JSON.parse(sessionStorage.getItem(KEY) || "{}");
} catch { /* storage unavailable: use URL only */ }

let signup = null, contact = "", slot = null;
const show = (n) => document.querySelectorAll(".step").forEach((s) => s.classList.toggle("active", s.id === `step-${n}`));

document.getElementById("signup").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  contact = String(f.get("phone")).trim();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  try {
    signup = await api.post("/api/public/signup", {
      name: String(f.get("name")).trim(), phone: contact, email: String(f.get("email") || "").trim() || null, ...attribution,
    });
    show(2);
    await loadServices();
  } catch (err) { toast(err.message, 4000); }
  finally { btn.disabled = false; }
});

async function loadServices() {
  const services = await api.get("/api/public/services");
  document.getElementById("svc").innerHTML = services.map((s) => `<option value="${s.id}">${esc(s.name)} · ${money(s.price)}</option>`).join("");
  const day = document.getElementById("day");
  day.min = isoDate(today());
  day.value = isoDate(addDays(today(), 1));
  await loadSlots();
}

async function loadSlots() {
  slot = null;
  document.getElementById("book").disabled = true;
  const box = document.getElementById("slots");
  const rows = await api.get(`/api/public/availability?day=${document.getElementById("day").value}&service_id=${document.getElementById("svc").value}`);
  box.innerHTML = rows.length ? rows.map((s, i) => `<button type="button" data-i="${i}" aria-pressed="false">${hhmm(s.start_at)}</button>`).join("")
    : `<p class="muted small">No openings that day - try another.</p>`;
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    slot = rows[+b.dataset.i];
    box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    document.getElementById("book").disabled = false;
  }));
}

document.getElementById("svc").addEventListener("change", loadSlots);
document.getElementById("day").addEventListener("change", loadSlots);
document.getElementById("book").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    const r = await api.post("/api/public/book", {
      signup_id: signup.signup_id, contact, service_id: +document.getElementById("svc").value, start_at: slot.start_at,
    });
    document.getElementById("done").textContent =
      parseLocal(r.start_at).toLocaleString([], { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" });
    show(3);
  } catch (err) { toast(err.message, 4000); e.target.disabled = false; }
});

// Small UI helpers: escaping, formatting, bottom sheets, toasts, dates.

export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export const money = (v, digits = 0) =>
  v == null ? "–" : Number(v).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: digits, minimumFractionDigits: digits });
export const num = (v, digits = 0) => (v == null ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits }));
export const pct = (v, digits = 0) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);

export const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// Backend dates are shop-local wall-clock strings; parse them without timezone shifts.
export const parseLocal = (s) => {
  const [d, t = "00:00"] = String(s).split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  return new Date(y, m - 1, day, hh, mm);
};
export const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
export const weekdayIdx = (d) => (d.getDay() + 6) % 7;   // Monday = 0, like the backend
export const hhmm = (s) => parseLocal(s).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
export const shortDate = (s) => parseLocal(s).toLocaleDateString([], { month: "short", day: "numeric" });
export const dayLabel = (s) => parseLocal(s).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
export const initials = (name) => esc(String(name || "?").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase());

export function toast(msg, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), ms);
}

// Bottom sheet on phones, centered dialog on wide screens.
export function sheet(title, html, onMount) {
  const root = document.getElementById("sheet-root");
  root.innerHTML = `
    <div class="sheet-backdrop" data-close></div>
    <section class="sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="grab"></div>
      <div class="sheet-head"><h2>${esc(title)}</h2><button class="btn ghost small" data-close aria-label="Close">Close</button></div>
      <div class="sheet-body">${html}</div>
    </section>`;
  const close = () => { root.innerHTML = ""; document.removeEventListener("keydown", onKey); };
  const onKey = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", onKey);
  root.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  const body = root.querySelector(".sheet-body");
  onMount?.(body, close);
  body.querySelector("input,select,button")?.focus({ preventScroll: true });
  return close;
}

// Wrap an async click handler: disable the button while it runs, surface errors as a toast.
export function busy(button, fn) {
  return async (...args) => {
    button.disabled = true;
    try { return await fn(...args); }
    catch (err) { toast(err.message || String(err), 4000); }
    finally { button.disabled = false; }
  };
}

export const statusChip = (status) => {
  const map = { booked: "", completed: "good", no_show: "bad", cancelled: "bad", ENABLED: "good", PAUSED: "warn", REMOVED: "bad",
                due: "", overdue: "warn", lapsed: "bad" };
  const label = String(status).replace("_", " ").toLowerCase();
  return `<span class="chip ${map[status] ?? ""}"><span class="dot"></span>${esc(label)}</span>`;
};

export const sourceChip = (source) =>
  source === "google_ads" || source === "gclid" || source === "utm" || source === "gclid_pending"
    ? `<span class="chip ads"><span class="dot"></span>${source === "gclid_pending" ? "Google Ads (matching)" : "Google Ads"}</span>`
    : `<span class="chip">${esc(String(source || "organic").replace("_", " "))}</span>`;

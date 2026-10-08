// Hash router + app bootstrap.
import { toast } from "./ui.js";

const routes = {
  today: () => import("./views/today.js"),
  schedule: () => import("./views/schedule.js"),
  clients: () => import("./views/clients.js"),
  growth: () => import("./views/growth.js"),
  more: () => import("./views/more.js"),
};

const view = document.getElementById("view");

async function render() {
  const [name, ...rest] = (location.hash.replace(/^#\/?/, "") || "today").split("/");
  const route = routes[name] ? name : "today";
  document.querySelectorAll(".tabs a").forEach((a) =>
    a.dataset.tab === route ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  document.getElementById("sheet-root").innerHTML = "";        // sheets belong to the screen that opened them
  document.getElementById("tooltip").classList.remove("show");
  view.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    const mod = await routes[route]();
    await mod.render(view, rest);
  } catch (err) {
    console.error(err);
    view.innerHTML = `<div class="card empty"><h2>Couldn't load this screen</h2><p class="muted">${String(err.message || err)}</p>
      <button class="btn" onclick="location.reload()">Retry</button></div>`;
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// Theme: system by default; Settings can pin light/dark.
try {
  const t = localStorage.getItem("tallyos-theme");
  if (t) document.documentElement.dataset.theme = t;
} catch { /* storage unavailable */ }

window.addEventListener("hashchange", render);
window.addEventListener("tallyos:refresh", render);
render();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
window.addEventListener("offline", () => toast("You're offline - showing cached screens"));

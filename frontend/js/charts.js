// Dependency-free SVG charts: stacked columns with a target line, and a sparkline.
// Colors are CSS variables (validated palette in app.css); every chart has a hover
// tooltip and a table view, since the aqua series is under 3:1 contrast on light.
import { esc } from "./ui.js";

const tip = () => document.getElementById("tooltip");

function showTip(evt, html) {
  const el = tip();
  el.innerHTML = html;
  el.classList.add("show");
  const pad = 12;
  const { innerWidth: W, innerHeight: H } = window;
  const r = el.getBoundingClientRect();
  const x = evt.clientX ?? evt.touches?.[0]?.clientX ?? 0;
  const y = evt.clientY ?? evt.touches?.[0]?.clientY ?? 0;
  el.style.left = `${Math.min(W - r.width - pad, Math.max(pad, x - r.width / 2))}px`;
  el.style.top = `${y - r.height - 14 < pad ? y + 18 : y - r.height - 14}px`;
}
const hideTip = () => tip().classList.remove("show");

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
}

// Rounded top corners only (data-end), square at the baseline.
function topRounded(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/**
 * rows:   [{ label, sub?, values: {key: n}, target?: n, extra?: [[k, v]] }]
 * series: [{ key, label, color }]   (bottom -> top stacking order)
 */
export function stackedColumns(el, opts) {
  const { rows, series, targetLabel, height = 200, valueFmt = (v) => v.toFixed(1) } = opts;
  const draw = () => {
    const W = Math.max(280, el.clientWidth);
    const m = { t: 10, r: 6, b: 34, l: 28 };
    const iw = W - m.l - m.r, ih = height - m.t - m.b;
    const totals = rows.map((r) => series.reduce((s, x) => s + (r.values[x.key] || 0), 0));
    const yMax = niceMax(Math.max(...totals, ...rows.map((r) => r.target || 0)));
    const y = (v) => m.t + ih - (v / yMax) * ih;
    const band = iw / rows.length;
    const bw = Math.max(6, Math.min(28, band * 0.62));
    const ticks = [0, yMax / 2, yMax];

    let svg = `<svg class="chart" width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" role="img">`;
    svg += `<g class="grid">${ticks.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>`).join("")}</g>`;
    svg += ticks.map((t) => `<text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${t % 1 ? t.toFixed(1) : t}</text>`).join("");
    rows.forEach((r, i) => {
      const cx = m.l + band * i + band / 2;
      let acc = 0;
      const present = series.filter((s) => (r.values[s.key] || 0) > 0);
      let marks = "";
      present.forEach((s, j) => {
        const v = r.values[s.key];
        const y0 = y(acc), y1 = y(acc + v);
        const h = Math.max(0, y0 - y1 - (j > 0 ? 2 : 0));   // 2px surface gap between stacked fills
        const top = y1;
        marks += j === present.length - 1
          ? `<path d="${topRounded(cx - bw / 2, top, bw, h, 4)}" fill="var(${s.color})"/>`
          : `<rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${h}" fill="var(${s.color})"/>`;
        acc += v;
      });
      if (r.target) {
        marks += `<line class="target" x1="${cx - band * 0.45}" x2="${cx + band * 0.45}" y1="${y(r.target)}" y2="${y(r.target)}"/>`;
      }
      const showLabel = rows.length <= 8 || i % 2 === 0;
      svg += `<g class="col">${marks}</g>`;
      if (showLabel) {
        svg += `<text x="${cx}" y="${height - 18}" text-anchor="middle">${esc(r.label)}</text>`;
        if (r.sub) svg += `<text x="${cx}" y="${height - 5}" text-anchor="middle">${esc(r.sub)}</text>`;
      }
      svg += `<rect class="hit" data-i="${i}" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}"/>`;
    });
    svg += `<line class="baseline" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/></svg>`;

    const legend = opts.legend === false ? "" : `<div class="legend">${series.map((s) => `<span><span class="sw" style="background:var(${s.color})"></span>${esc(s.label)}</span>`).join("")}
      ${targetLabel ? `<span><span class="sw line"></span>${esc(targetLabel)}</span>` : ""}</div>`;
    el.innerHTML = svg + legend;

    el.querySelectorAll(".hit").forEach((h) => {
      const r = rows[+h.dataset.i];
      const html = `<div><b>${esc(r.label)} ${esc(r.sub || "")}</b></div>` +
        series.map((s) => `<div class="row"><span><span class="sw" style="display:inline-block;width:8px;height:8px;border-radius:2px;background:var(${s.color});margin-right:5px"></span>${esc(s.label)}</span><b>${valueFmt(r.values[s.key] || 0)}</b></div>`).join("") +
        (r.target != null ? `<div class="row"><span>${esc(targetLabel || "Target")}</span><b>${valueFmt(r.target)}</b></div>` : "") +
        (r.extra || []).map(([k, v]) => `<div class="row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
      const on = (e) => showTip(e, html);
      h.addEventListener("pointermove", on);
      h.addEventListener("pointerdown", on);
      h.addEventListener("pointerleave", hideTip);
    });
  };
  draw();
  const ro = new ResizeObserver(() => { if (el.isConnected) draw(); else ro.disconnect(); });
  ro.observe(el);
}

export function dataTable(rows, series, targetLabel, valueFmt = (v) => v.toFixed(1)) {
  return `<div class="table-wrap"><table class="data"><thead><tr><th>Day</th>${series.map((s) => `<th>${esc(s.label)}</th>`).join("")}${targetLabel ? `<th>${esc(targetLabel)}</th>` : ""}</tr></thead><tbody>
    ${rows.map((r) => `<tr><td>${esc(r.label)} ${esc(r.sub || "")}</td>${series.map((s) => `<td>${valueFmt(r.values[s.key] || 0)}</td>`).join("")}${targetLabel ? `<td>${r.target != null ? valueFmt(r.target) : "–"}</td>` : ""}</tr>`).join("")}
  </tbody></table></div>`;
}

// Chart + "Chart | Table" toggle in one card body.
export function chartWithTable(el, opts) {
  el.innerHTML = `<div class="seg" role="group" aria-label="View" style="margin-bottom:8px">
      <button aria-pressed="true" data-v="chart">Chart</button><button aria-pressed="false" data-v="table">Table</button></div>
    <div data-slot></div>`;
  const slot = el.querySelector("[data-slot]");
  const show = (v) => {
    el.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    if (v === "chart") stackedColumns(slot, opts);
    else slot.innerHTML = dataTable(opts.rows, opts.series, opts.targetLabel, opts.valueFmt);
  };
  el.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => show(b.dataset.v)));
  show("chart");
}

// Single-series sparkline (no legend: the caption names it).
export function sparkline(values, { width = 120, height = 32, color = "--series-1" } = {}) {
  if (!values.length) return "";
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - (v / max) * (height - 6)).toFixed(1)}`);
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <polyline points="${pts.join(" ")}" fill="none" stroke="var(${color})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

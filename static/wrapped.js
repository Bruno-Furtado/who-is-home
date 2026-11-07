"use strict";
// Wrapped: o mês da casa em números grandes, recordes e um cartão por pessoa.
const { t, $, esc, mins, num } = WH;
WH.applyStatic();
WH.markTab("people");
WH.initTips();

let month = new URLSearchParams(location.search).get("month") || "";
const F_MONTH = new Intl.DateTimeFormat(WH.locale, { month: "long", year: "numeric" });
const F_DAY = new Intl.DateTimeFormat(WH.locale, { weekday: "long", day: "numeric" });
const hours = (m) => Math.round(m / 60);
const card = (inner, cls = "", color = "") => `<div class="card wr-card ${cls}"${color ? ` style="--sc:${color}"` : ""}>${inner}</div>`;
const k = (key, vars) => `<div class="wr-k">${esc(t(key, vars))}</div>`;

function shift(m, delta) {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(y, mo - 1 + delta, 1);
  return `${d.getFullYear()}-${WH.pad(d.getMonth() + 1)}`;
}

function personCard(p) {
  const top = p.apps.find((a) => a.minutes || a.queries);
  const cat = p.categories[0];
  const facts = [
    [t("wr.topApp"), top ? esc(top.app) : "—"],
    [t("wr.topCat"), cat ? esc(WH.cat(cat.cat).label) : "—"],
    [t("pp.routine"), p.start ? `${p.start}–${p.end}` : "—"],
    [t("pp.work"), mins(p.work_minutes)],
  ];
  return card(`<div class="wr-person">
    <div class="p-head">${WH.avatar(p.name, "lg")}<b>${esc(p.name)}</b></div>
    <div><div class="wr-big">${hours(p.minutes)}<small> h</small></div><div class="wr-sub">${esc(t("pp.perDay", { v: mins(p.per_day) }))}</div></div>
    ${WH.catStrip(p.categories)}
    ${p.titles.length ? `<div class="titles">${p.titles.map(WH.titleChip).join("")}</div>` : ""}
    <div class="wr-facts">${facts.map(([l, v]) => `<div><span>${esc(l)}</span><b>${v}</b></div>`).join("")}</div>
  </div>`, "glow");
}

function render(w) {
  month = w.month;
  const [y, mo] = w.month.split("-").map(Number);
  const label = F_MONTH.format(new Date(y, mo - 1, 1));
  $("#month").textContent = label.charAt(0).toUpperCase() + label.slice(1);
  $("#prev").disabled = !w.months.length || w.month <= w.months[0];
  const today = new Date();
  $("#next").disabled = w.month >= `${today.getFullYear()}-${WH.pad(today.getMonth() + 1)}`;
  history.replaceState(null, "", "/wrapped?month=" + w.month);
  if (!w.minutes && !w.queries) { $("#wr").innerHTML = `<div class="card wr-card wide wr-empty">${esc(t("wr.empty"))}</div>`; return; }

  const out = [];
  // a casa
  out.push(card(`${k("wr.house")}<div class="wr-big">${hours(w.minutes)}<small> h</small></div>
    <div class="wr-sub">${esc(t("wr.houseSub", { d: w.days, s: num(w.sites) }))}</div>`, "wide glow", "var(--accent)"));
  if (w.apps.length) {
    const byMin = w.apps.some((a) => a.minutes);
    out.push(card(`${k("wr.apps")}<ol class="rank">${w.apps.slice(0, 5).map((a, i) =>
      `<li><i>${i + 1}</i>${esc(a.app)}<span>${byMin ? mins(a.minutes) : num(a.queries)}</span></li>`).join("")}</ol>`, "glow", "var(--c-social)"));
  }
  if (w.peak_hour != null) {
    out.push(card(`${k("wr.peak")}<div class="wr-big">${WH.hourLabel(w.peak_hour)}</div>
      ${w.busiest_day ? `<div class="wr-sub">${esc(t("wr.busiest", { d: F_DAY.format(new Date(w.busiest_day.day + "T12:00:00")), h: mins(w.busiest_day.minutes) }))}</div>` : ""}`, "glow", "var(--c-games)"));
  }
  // cada pessoa
  w.people.filter((p) => p.minutes).forEach((p) => out.push(personCard(p)));
  // recordes
  const r = w.records;
  if (r.streak) out.push(card(`${k("wr.streak")}<div class="wr-mid">${mins(r.streak.minutes)}</div>
    <div class="wr-sub">${esc(r.streak.name)} · ${esc(WH.dt(r.streak.ts))}</div>`, "glow", "var(--ok)"));
  if (r.latest) out.push(card(`${k("wr.latest")}<div class="wr-mid">${esc(r.latest.time)}</div>
    <div class="wr-sub">🦉 ${esc(r.latest.name)}</div>`, "glow", "var(--accent-2)"));
  // privacidade e rede
  out.push(card(`${k("wr.blocked")}<div class="wr-mid">${num(w.blocked)}</div>
    <div class="wr-sub">${w.tracker ? esc(t("wr.tracker", { d: w.tracker.domain })) : ""}</div>`, "glow", "var(--down)"));
  if (w.internet && w.internet.outages != null) {
    out.push(card(`${k("wr.internet")}<div class="wr-mid">${w.internet.outages ? esc(w.internet.outages === 1 ? t("wr.outage1") : t("wr.outages", { n: w.internet.outages })) : "✓"}</div>
      <div class="wr-sub">${esc(w.internet.outages ? t("wr.down", { d: WH.secs(w.internet.down_s) }) : t("wr.noOutages"))}</div>`, "glow", "var(--warn)"));
  }
  if (w.new_devices.length) out.push(card(`${k("wr.new")}<div class="wr-mid">${w.new_devices.length}</div>
    <div class="wr-sub">${esc(w.new_devices.slice(0, 4).join(", "))}${w.new_devices.length > 4 ? "…" : ""}</div>`, "glow", "var(--c-messaging)"));
  $("#wr").innerHTML = out.join("");
}

async function load() {
  try { render(await WH.get("/api/wrapped?month=" + encodeURIComponent(month))); }
  catch (e) { $("#wr").innerHTML = `<div class="card wr-card wide wr-empty">${esc(t("err.load"))}</div>`; }
}
$("#prev").onclick = () => { month = shift(month, -1); load(); };
$("#next").onclick = () => { month = shift(month, 1); load(); };
load();

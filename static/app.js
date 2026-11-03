"use strict";
// Painel principal: quem está online, aparelhos e relatório do período.
const { t, $, esc, mins, num } = WH;
WH.applyStatic();
WH.mountLangMenu($("#lang"), $("#lang-menu"));
WH.mountThemeMenu($("#theme"), $("#theme-menu"));
WH.initTips();

let period = WH.store.get("period", "today");
let filter = WH.store.get("filter", "all");
let sort = WH.store.get("sort", "usage");
let devices = [];
let cfg = {};

const devHref = (mac) => "/device?mac=" + encodeURIComponent(mac);

/* ---------- topo: agora, hoje, internet ---------- */
function renderNow(n) {
  $("#now-card").classList.toggle("is-idle", !n.online);
  $("#now-big").innerHTML = `${n.online} <small class="muted">/ ${n.total}</small>`;
  $("#now-sub").textContent = t("now.sub", { time: WH.time(n.now) });
  const st = n.status || {};
  const box = $("#setup");
  if (st.adguard === "unset" || st.adguard === "error") {
    box.hidden = false;
    $("#setup-title").textContent = t(st.adguard === "unset" ? "setup.unsetTitle" : "setup.errorTitle");
    $("#setup-body").innerHTML = st.adguard === "unset" ? t("setup.unsetBody") : esc(t("setup.errorBody", { err: st.adguard_error || "?" }));
  } else box.hidden = true;
}

function renderToday(o) {
  const tot = o.totals;
  const tiles = [
    [t("today.minutes"), mins(tot.minutes), t("today.minutesHint")],
    [t("today.queries"), num(tot.queries), t("today.queriesHint")],
    [t("today.blocked"), num(tot.blocked), t("today.blockedHint", { p: WH.pct(tot.blocked, tot.queries) })],
    [t("today.new"), num(tot.new_devices), t("today.newHint")],
  ];
  $("#today-tiles").innerHTML = tiles.map(([l, v, h]) => `<div class="gl-tile" data-tip="${esc(h)}"><span>${esc(l)}</span><b>${v}</b></div>`).join("");
}

function renderNet(n) {
  const card = $("#net-card");
  $(".hero").classList.toggle("no-net", !n.enabled);
  if (!n.enabled) { card.hidden = true; return; }
  card.hidden = false;
  card.href = n.port ? `http://${location.hostname}:${n.port}` : "#";
  const ic = $("#net-ic");
  ic.className = "gl-ic" + (!n.ok ? " idle" : n.state === "up" ? "" : " bad");
  if (!n.ok) {
    $("#net-title").textContent = t("net.unreachable");
    $("#net-sub").textContent = t("net.unreachableHint");
    return;
  }
  const up = n.state === "up";
  $("#net-title").textContent = up ? t("net.up") : t("net.down");
  const outages = (n.h24 && n.h24.count) || 0;
  const parts = [outages === 1 ? t("net.outage1") : t("net.outages", { n: outages })];
  if (n.speed && n.speed.down) parts.push(t("net.speed", { down: Math.round(n.speed.down), up: Math.round(n.speed.up || 0) }));
  $("#net-sub").textContent = parts.join(" · ");
}

/* ---------- aparelhos ---------- */
function devSub(d) {
  const bits = [esc(d.ip || "")];
  if (d.private_mac) bits.push(`<span class="badge" data-tip="${esc(t("dev.privateHint"))}">${esc(t("dev.private"))}</span>`);
  return bits.join(" ");
}

function renderDevices() {
  let list = devices.slice();
  if (filter === "online") list = list.filter((d) => d.online);
  if (filter === "offline") list = list.filter((d) => !d.online);
  if (sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, WH.locale));
  else if (sort === "recent") list.sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0));
  else list.sort((a, b) => (b.online - a.online) || (b.today_minutes - a.today_minutes) || ((b.last_seen || 0) - (a.last_seen || 0)));
  const online = devices.filter((d) => d.online).length;
  $("#dev-desc").textContent = t("dev.desc", { n: devices.length, on: online });
  if (!list.length) { $("#devices").innerHTML = `<div class="card empty"><b>${esc(t("dev.none"))}</b>${esc(t("dev.noneHint"))}</div>`; return; }
  const maxMin = Math.max(30, ...devices.map((d) => d.today_minutes));
  const now = Date.now() / 1000;
  $("#devices").innerHTML = list.map((d) => {
    const status = d.online ? `<span class="dot on"></span>${esc(t("dev.isOnline"))}` : `<span class="dot"></span>${esc(t("dev.seen", { ago: WH.ago(d.last_seen, now) }))}`;
    const top = d.top_cat ? WH.catChip(d.top_cat) : "";
    return `<a class="card dev${d.online ? " on" : ""}" href="${devHref(d.mac)}">
      <span class="dev-ic">${WH.kindIcon(d.kind)}</span>
      <span class="dev-main"><b>${esc(d.name)}</b><small>${devSub(d)}</small><small class="dev-st">${status}</small></span>
      <span class="dev-use"><b>${mins(d.today_minutes)}</b><small>${esc(t("dev.today"))}</small>
        <span class="dev-bar"><i style="width:${(d.today_minutes / maxMin) * 100}%"></i></span>${top}</span>
    </a>`;
  }).join("");
}

/* ---------- relatório do período ---------- */
function renderReport(o) {
  const tot = o.totals;
  const days = o.days.length;
  $("#rep-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const kpis = [
    [t("kpi.minutes"), mins(tot.minutes), t("kpi.minutesSub", { n: tot.active_devices }), "var(--accent)"],
    [t("kpi.queries"), num(tot.queries), t("kpi.queriesSub", { n: num(Math.round(tot.queries / days)) }), "var(--ok)"],
    [t("kpi.blocked"), num(tot.blocked), t("kpi.blockedSub", { p: WH.pct(tot.blocked, tot.queries) }), "var(--down)"],
    [t("kpi.new"), num(tot.new_devices), t("kpi.newSub"), "var(--warn)"],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v, s, c]) => `<div class="card kpi"><h3><i style="--c:${c}"></i>${esc(l)}</h3><b>${v}</b><small>${esc(s)}</small></div>`).join("");
  $("#usage").innerHTML = WH.barsHTML(o.usage.slice(0, 12).map((u) => ({
    label: u.name, value: u.minutes, icon: `<span class="mini-ic">${WH.kindIcon(u.kind)}</span>`, href: devHref(u.mac),
  })), mins);
  $("#cats").innerHTML = WH.catsHTML(o.categories);
  $("#hours").innerHTML = WH.hoursHTML(o.hours);
  $("#sites").innerHTML = domainList(o.top_domains, "queries");
  $("#blocked").innerHTML = domainList(o.blocked, "blocked");
  $("#night-hint").textContent = t("rep.nightHint", { a: o.night_from, b: o.night_to });
  $("#night").innerHTML = o.night.length ? WH.barsHTML(o.night.map((u) => ({
    label: u.name, value: u.minutes, icon: `<span class="mini-ic">${WH.kindIcon(u.kind)}</span>`, href: devHref(u.mac), color: "var(--accent-2)",
  })), mins) : `<div class="empty">${esc(t("rep.nightNone"))}</div>`;
  $("#events").innerHTML = o.events.length ? `<div class="events">${o.events.map((e) => `
    <a class="ev" href="${devHref(e.mac)}"><span class="dot new"></span><span><b>${esc(t("ev." + e.kind, { name: e.name }))}</b><small>${esc(WH.dt(e.ts))} · ${esc(e.detail || "")}</small></span></a>`).join("")}</div>`
    : `<div class="empty">${esc(t("rep.eventsNone"))}</div>`;
}

function domainList(rows, field) {
  if (!rows.length) return `<div class="empty">${esc(t(field === "blocked" ? "rep.blockedNone" : "empty.period"))}</div>`;
  const max = Math.max(1, ...rows.map((r) => r[field]));
  return `<div class="dlist">${rows.map((r) => `<div class="drow">
    <span class="d-name"><b>${esc(r.domain)}</b>${WH.catChip(r.cat)}</span>
    <span class="num">${num(r[field])}<small>${esc(r.devices === 1 ? t("rep.device1") : t("rep.devices", { n: r.devices }))}</small></span>
    <span class="bar-t"><i style="width:${(r[field] / max) * 100}%;background:${field === "blocked" ? "var(--down)" : WH.cat(r.cat).color}"></i></span>
  </div>`).join("")}</div>`;
}

/* ---------- carga ---------- */
async function loadTop() {
  const [n, devs] = await Promise.all([WH.get("/api/now"), WH.get("/api/devices")]);
  devices = devs;
  renderNow(n);
  renderDevices();
}
async function loadToday() { renderToday(await WH.get("/api/overview?period=today")); }
async function loadReport() { renderReport(await WH.get("/api/overview?period=" + period)); }
async function loadNet() { renderNet(await WH.get("/api/internet")); }

async function loadAll() {
  $("#refresh").classList.add("spin");
  try { await Promise.all([loadTop(), loadToday(), loadReport(), loadNet()]); }
  catch (e) { $("#now-sub").textContent = t("err.load"); }
  finally { $("#refresh").classList.remove("spin"); }
}

WH.seg($("#dev-filter"), filter, (v) => { filter = v; WH.store.set("filter", v); renderDevices(); });
WH.seg($("#period-seg"), period, (v) => { period = v; WH.store.set("period", v); loadReport(); });
$("#dev-sort").value = sort;
$("#dev-sort").onchange = (e) => { sort = e.target.value; WH.store.set("sort", sort); renderDevices(); };
$("#refresh").onclick = loadAll;

$("#test").onclick = async () => {
  const r = await WH.post("/api/test-notify");
  const res = $("#test-res");
  res.className = "res " + (r.ok ? "ok" : "bad");
  res.textContent = r.ok ? t("ntfy.sent") : t("ntfy.err." + (r.code || "send_failed"), { s: r.wait || "" });
};

WH.get("/api/config").then((c) => {
  cfg = c;
  $("#ntfy-desc").textContent = c.ntfy ? t("ntfy.on") : t("ntfy.off");
  $("#test").hidden = !c.ntfy;
  $("#foot").textContent = `who-is-home ${c.version} · ${c.host || c.ip || ""}`;
}).catch(() => {});

loadAll();
setInterval(() => { if (!document.hidden) loadAll(); }, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadAll(); });

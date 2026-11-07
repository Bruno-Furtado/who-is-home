"use strict";
// Painel principal: quem está online, pessoas, aparelhos e relatório do período.
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
let editing = null;          // id da pessoa sendo editada ('new' = criando)
let peopleData = null;

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
  if (d.members && d.members.length) bits.push(`<span class="badge infra" data-tip="${esc(t("dev.linksHint", { n: d.members.length + 1 }))}">+${d.members.length}</span>`);
  if (d.hidden) bits.push(`<span class="badge infra" data-tip="${esc(t("dev.infraHint"))}">${esc(t("dev.infra"))}</span>`);
  else if (d.private_mac) bits.push(`<span class="badge" data-tip="${esc(t("dev.privateHint"))}">${esc(t("dev.private"))}</span>`);
  return bits.join(" ");
}

function renderDevices() {
  let list = devices.slice();
  if (filter === "online") list = list.filter((d) => d.online);
  if (filter === "offline") list = list.filter((d) => !d.online);
  if (sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, WH.locale));
  else if (sort === "recent") list.sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0));
  else list.sort((a, b) => (a.hidden - b.hidden) || (b.online - a.online) || (b.today_minutes - a.today_minutes) || ((b.last_seen || 0) - (a.last_seen || 0)));
  const online = devices.filter((d) => d.online).length;
  $("#dev-desc").textContent = t("dev.desc", { n: devices.length, on: online });
  if (!list.length) { $("#devices").innerHTML = `<div class="card empty"><b>${esc(t("dev.none"))}</b>${esc(t("dev.noneHint"))}</div>`; return; }
  const maxMin = Math.max(30, ...devices.map((d) => d.today_minutes));
  const now = Date.now() / 1000;
  $("#devices").innerHTML = list.map((d) => {
    const status = d.online ? `<span class="dot on"></span>${esc(t("dev.isOnline"))}` : `<span class="dot"></span>${esc(t("dev.seen", { ago: WH.ago(d.last_seen, now) }))}`;
    const top = d.person ? `<span class="who">${WH.avatar(d.person, "sm")}${esc(d.person)}</span>` : d.top_cat ? WH.catChip(d.top_cat) : "";
    return `<a class="card dev${d.online ? " on" : ""}${d.hidden ? " infra" : ""}" href="${devHref(d.mac)}">
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
  $("#apps").innerHTML = appsHTML(o.apps);
  $("#sites").innerHTML = domainList(o.top_domains, "queries");
  $("#blocked").innerHTML = domainList(o.blocked, "blocked");
  $("#night-title").textContent = t("rep.nightTitle", { a: o.night_from, b: o.night_to });
  $("#night").innerHTML = o.night.length ? WH.barsHTML(o.night.map((u) => ({
    label: u.name, value: u.minutes, icon: `<span class="mini-ic">${WH.kindIcon(u.kind)}</span>`, href: devHref(u.mac), color: "var(--accent-2)",
  })), mins) : `<div class="empty">${esc(t("rep.nightNone"))}</div>`;
  $("#events").innerHTML = o.events.length ? `<div class="events">${o.events.map((e) => `
    <a class="ev" href="${devHref(e.mac)}"><span class="dot new"></span><span><b>${esc(t("ev." + e.kind, { name: e.name }))}</b><small>${esc(WH.dt(e.ts))} · ${esc(e.detail || "")}</small></span></a>`).join("")}</div>`
    : `<div class="empty">${esc(t("rep.eventsNone"))}</div>`;
}

// Apps: por minutos quando já há (dados novos), senão por consultas.
function appsHTML(apps) {
  if (!apps || !apps.length) return `<div class="empty">${esc(t("empty.period"))}</div>`;
  const byMin = apps.some((a) => a.minutes);
  const val = (a) => (byMin ? a.minutes : a.queries);
  return WH.barsHTML(apps.filter(val).slice(0, 8).map((a) => ({ label: a.app, value: val(a), color: "var(--accent-2)" })), byMin ? mins : num);
}

/* ---------- pessoas ---------- */
const PENCIL = '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/></svg>';

function personCard(p, days) {
  if (editing === p.id) return personForm(p);
  const stat = (label, value, tip) => `<div data-tip="${esc(tip)}"><span>${esc(label)}</span><b>${value}</b></div>`;
  const routine = p.start ? `${p.start}–${p.end}` : "—";   // tile largo (ocupa 2 colunas no celular)
  const apps = (p.apps || []).filter((a) => a.minutes || a.queries).slice(0, 3).map((a) => esc(a.app));
  return `<div class="card person">
    <div class="p-head">${WH.avatar(p.name)}<b>${esc(p.name)}</b>
      <button class="icon-btn sm" data-edit="${p.id}" data-i18n-title="pp.edit" title="${esc(t("pp.edit"))}">${PENCIL}</button></div>
    <div class="p-hours"><b>${mins(p.minutes)}</b><span>${days > 1 && p.days_active ? esc(t("pp.perDay", { v: mins(p.per_day) })) : ""}</span></div>
    ${WH.catStrip(p.categories)}
    ${p.titles.length ? `<div class="titles">${p.titles.slice(0, 3).map(WH.titleChip).join("")}</div>` : ""}
    <div class="p-stats">
      ${stat("💼 " + t("pp.work"), mins(p.work_minutes), p.work_start ? t("pp.workHint", { a: p.work_start, b: p.work_end }) : t("pp.work"))}
      ${p.home_s != null ? stat("🏠 " + t("pp.home"), WH.secs(p.home_s), t("pp.homeHint")) : stat("🌙 " + t("pp.night"), mins(p.night_minutes), t("pp.nightHint"))}
      ${stat("🕘 " + t("pp.routine"), routine, t("pp.routineHint"))}
    </div>
    ${apps.length ? `<div class="p-apps">${apps.map((a) => `<b>${a}</b>`).join(" · ")}</div>` : ""}
  </div>`;
}

function personForm(p) {
  return `<div class="card person"><form class="p-edit" data-form="${p ? p.id : "new"}">
    <input name="name" maxlength="30" value="${p ? esc(p.name) : ""}" placeholder="${esc(t("pp.name"))}" autocomplete="off">
    <button class="btn primary" type="submit">${esc(t("edit.save"))}</button>
    ${p ? `<button class="btn" type="button" data-del="${p.id}">${esc(t("pp.delete"))}</button>` : ""}
    <button class="btn" type="button" data-cancel>${esc(t("edit.cancel"))}</button>
  </form></div>`;
}

function renderPeople(x) {
  peopleData = x;
  const days = x.days.length;
  $("#pp-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const cards = x.people.map((p) => personCard(p, days));
  cards.push(editing === "new" ? personForm(null) : `<button class="card add-card" data-add>+ ${esc(t("pp.add"))}</button>`);
  $("#people").innerHTML = cards.join("");
  const un = $("#unassigned");
  un.hidden = !x.people.length || !x.unassigned.length;
  un.innerHTML = `${esc(t("pp.unassigned"))} ${x.unassigned.map((d) => `<a href="${devHref(d.mac)}">${esc(d.name)}</a>`).join(", ")}`;
  const input = $("#people input[name=name]");
  if (input) input.focus();
}

$("#people").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.add !== undefined) { editing = "new"; return renderPeople(peopleData); }
  if (b.dataset.edit) { editing = Number(b.dataset.edit); return renderPeople(peopleData); }
  if (b.dataset.cancel !== undefined) { editing = null; return renderPeople(peopleData); }
  if (b.dataset.del && confirm(t("pp.confirmDelete"))) {
    await WH.post("/api/person", { id: Number(b.dataset.del), delete: true });
    editing = null;
    loadAll();
  }
});
$("#people").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, name = f.elements.name.value.trim();
  if (!name) return;
  const id = f.dataset.form === "new" ? null : Number(f.dataset.form);
  const r = await WH.post("/api/person", { id, name });
  if (r.ok) { editing = null; loadAll(); }
});

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
async function loadReport() {
  const [o, p] = await Promise.all([WH.get("/api/overview?period=" + period), WH.get("/api/people?period=" + period)]);
  renderReport(o);
  if (editing === null) renderPeople(p); else peopleData = p;
}
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

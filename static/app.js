"use strict";
// Painel principal em abas (igual ao down-again): Agora, Pessoas, Aparelhos, Relatório e Ajustes.
const { t, $, esc, mins, num } = WH;
WH.applyStatic();
WH.initTips();

const S = {
  tab: "now", period: WH.store.get("period", "7d"), filter: WH.store.get("filter", "all"), sort: WH.store.get("sort", "usage"),
  devices: [], people: null, editing: null, cfg: null,
};
const devHref = (mac) => "/device?mac=" + encodeURIComponent(mac);
// Só mexe no DOM quando o conteúdo muda: o painel fica aberto o dia todo.
const setHTML = (el, v) => { if (el._html !== v) { el.innerHTML = v; el._html = v; } };
const ICON = {
  arrive: '<path d="M3 12h12M11 8l4 4-4 4"/><path d="M15 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/>',
  leave: '<path d="M21 12H9M13 8l-4 4 4 4"/><path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/>',
  new: '<path d="M12 5v14M5 12h14"/>',
};

/* ---------- abas ---------- */
const TABS = ["now", "people", "devices", "report", "settings"];
function showTab(tab) {
  if (!TABS.includes(tab)) tab = "now";
  S.tab = tab;
  TABS.forEach((x) => { $("#v-" + x).hidden = x !== tab; });
  WH.markTab(tab);
  // o mesmo seletor de período serve a Pessoas e ao Relatório
  (tab === "report" ? $("#report-period-slot") : $("#people-period-slot")).appendChild($("#period-seg"));
  load();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

/* ---------- topo: internet (down-again) e aviso de configuração ---------- */
function renderNet(n) {
  const chip = $("#netchip");
  chip.hidden = !n.enabled;
  if (!n.enabled) return;
  chip.href = n.port ? `http://${location.hostname}:${n.port}` : "#";
  $("#netdot").className = "dot" + (n.ok && n.state === "up" ? " on" : "");
  $("#netname").textContent = !n.ok ? t("net.unreachable") : n.state === "up" ? t("net.up") : t("net.down");
  const parts = [];
  if (n.ok) {
    const c = (n.h24 && n.h24.count) || 0;
    parts.push(c === 1 ? t("net.outage1") : t("net.outages", { n: c }));
    if (n.speed && n.speed.down) parts.push(t("net.speed", { down: Math.round(n.speed.down), up: Math.round(n.speed.up || 0) }));
  }
  chip.dataset.tip = esc(parts.join(" · "));
}
function renderSetup(st) {
  const box = $("#setup");
  box.hidden = !(st.adguard === "unset" || st.adguard === "error");
  if (box.hidden) return;
  $("#setup-title").textContent = t(st.adguard === "unset" ? "setup.unsetTitle" : "setup.errorTitle");
  $("#setup-body").innerHTML = st.adguard === "unset" ? t("setup.unsetBody") : esc(t("setup.errorBody", { err: st.adguard_error || "?" }));
}

/* ---------- Agora ---------- */
function renderNow(n, today, p) {
  const st = n.status || {};
  const ok = st.adguard === "ok" || st.adguard === "demo";
  $("#status").className = "hero " + (ok ? (n.online ? "" : "is-idle") : "is-warn");
  $("#st-title").textContent = ok ? t("now.pill") : t("now.pillOff");
  // quem está em casa: pelas pessoas (celular/relógio online); sem pessoas cadastradas, pelos aparelhos
  if (p.people.length) {
    const home = p.people.filter((x) => x.devices.some((d) => d.online));
    $("#st-lbl").textContent = t("now.lblPeople");
    setHTML($("#st-num"), `${home.length}<span class="dec"> / ${p.people.length}</span>`);
    setHTML($("#home-row"), p.people.map((x) => {
      const on = home.includes(x);
      return `<span class="who-at${on ? "" : " away"}" data-tip="${esc(on ? t("pp.athome") : t("pp.away"))}">${WH.avatar(x.name, "sm")}${esc(x.name)}</span>`;
    }).join(""));
  } else {
    $("#st-lbl").textContent = t("now.lbl");
    setHTML($("#st-num"), `${n.online}<span class="dec"> / ${n.total}</span>`);
    setHTML($("#home-row"), "");
  }
  setHTML($("#st-sub"), t("now.sub", { time: `<b>${mins(today.totals.minutes)}</b>`, q: `<b>${num(today.totals.queries)}</b>`, b: `<b>${num(today.totals.blocked)}</b>` }));
  renderSetup(st);
  // últimas 24h: trechos em que alguém estava usando
  const d = n.day, span = d.to - d.from, P = (x) => ((x - d.from) / span) * 100;
  setHTML($("#day-sum"), `<b>${esc(t("now.day"))}</b><span>${esc(t("now.daySub", { time: mins(d.busy_minutes) }))}</span>`);
  // trechos com menos de 10 min de intervalo viram um só (a faixa fica legível, sem cara de código de barras)
  const spans = [];
  for (const [a, b] of d.active) {
    if (spans.length && a - spans[spans.length - 1][1] < 600) spans[spans.length - 1][1] = b; else spans.push([a, b]);
  }
  setHTML($("#day-track"), spans.map(([a, b]) => `<i class="s-act" style="left:${P(a)}%;width:${Math.max(0.3, P(b) - P(a))}%"></i>`).join(""));
  const ticks = [0, 0.25, 0.5, 0.75].map((f) => WH.time(d.from + span * f));
  setHTML($("#day-ticks"), ticks.map((x) => `<span>${x}</span>`).join("") + `<span>${esc(t("now.nowTick"))}</span>`);
}

// Resumo do dia em frases curtas
function factHTML(f) {
  const time = (m) => `<b>${mins(m)}</b>`;
  const who = () => `<b>${esc(f.name)}</b>`;
  const map = {
    top: () => ["🏆", t("ins.top", { name: who(), time: time(f.time) }) + (f.cat ? ` · ${esc(WH.cat(f.cat).label.toLowerCase())}` : "")],
    work: () => ["💼", t("ins.work", { name: who(), time: time(f.time) })],
    social: () => ["📱", t("ins.social", { name: who(), time: time(f.time) })],
    night: () => ["🦉", t("ins.night", { name: who(), time: time(f.time) })],
    vs: () => [f.pct >= 0 ? "📈" : "📉", t(f.pct >= 0 ? "ins.vsUp" : "ins.vsDown", { p: `<b>${Math.abs(f.pct)}%</b>` })],
    peak: () => ["⏰", t("ins.peak", { h: `<b>${WH.hourLabel(f.hour)}</b>` })],
    app: () => ["⭐", t("ins.app", { app: `<b>${esc(f.app)}</b>` })],
    blocked: () => ["🛡️", t("ins.blocked", { n: `<b>${num(f.n)}</b>`, p: f.pct })],
  };
  const [icon, text] = (map[f.code] || (() => ["•", ""]))();
  return `<div class="fact"><span>${icon}</span><span>${text}</span></div>`;
}

function renderInsights(x) {
  setHTML($("#facts"), x.facts.length ? x.facts.slice(0, 5).map(factHTML).join("") : `<div class="empty">${esc(t("ins.none"))}</div>`);
  // pendências: só uma faixa curta com o total; a lista fica na aba Aparelhos
  const pending = new Set([...x.todo.no_name, ...x.todo.no_owner, ...x.todo.no_kind].map((d) => d.mac)).size;
  const bar = $("#todo-bar");
  bar.hidden = !pending && x.people > 0;
  bar.href = x.people ? "#devices" : "#people";
  $("#todo-bar-txt").textContent = x.people ? t("todo.bar", { n: pending }) : t("todo.noPeople");
}

// Aparelhos: o que falta organizar, calculado da própria lista
function renderTodo(devs) {
  const counted = devs.filter((d) => !d.hidden);
  const anyOwner = counted.some((d) => d.person);
  const groups = [
    ["todo.noName", counted.filter((d) => !d.nickname)],
    ["todo.noOwner", anyOwner ? counted.filter((d) => !d.person) : []],
    ["todo.noKind", counted.filter((d) => !d.kind)],
  ].filter(([, list]) => list.length);
  $("#todo-card").hidden = !groups.length;
  setHTML($("#todo"), groups.map(([label, list]) => `<div class="todo-g"><b>${esc(t(label, { n: list.length }))}</b><div class="todo-l">${
    list.map((d) => `<a class="chip-s" href="${devHref(d.mac)}">${esc(d.name)}</a>`).join("")}</div></div>`).join(""));
}

function renderRecent(rows, limit = 6) {
  if (!rows.length) { setHTML($("#recent"), `<div class="empty">${esc(t("recent.none"))}</div>`); return; }
  let last = "";
  const out = [];
  for (const r of rows.slice(0, limit)) {
    const day = WH.dayLabel(r.ts);
    if (day !== last) { out.push(`<div class="tx-day">${esc(day)}</div>`); last = day; }
    const color = { arrive: "var(--ok)", leave: "var(--muted)", new: "var(--warn)" }[r.kind];
    const amt = r.kind === "arrive" && r.secs ? t("recent.away", { d: WH.secs(r.secs) }) : r.kind === "leave" && r.secs ? t("recent.home", { d: WH.secs(r.secs) }) : "";
    out.push(`<a class="tx-row" href="${devHref(r.mac)}" style="--c:${color}"><span class="tx-ic"><svg viewBox="0 0 24 24">${ICON[r.kind]}</svg></span>
      <span class="tx-main"><b>${esc(t("recent." + r.kind, { name: r.name }))}</b><small>${esc(WH.time(r.ts))}${r.kind === "new" ? " · " + esc(r.device) : ""}</small></span>
      <span class="tx-amt"><small class="muted">${esc(amt)}</small></span></a>`);
  }
  setHTML($("#recent"), out.join(""));
}

// Lado a lado, a Atividade mostra só as linhas que cabem na altura do "Hoje" (nenhum dos dois fica com sobra).
function fitRecent(rows) {
  renderRecent(rows, 8);
  if (window.innerWidth <= 860) return;          // no celular os cartões ficam um embaixo do outro
  const target = $("#facts").getBoundingClientRect().height;
  for (let n = 7; n >= 3 && $("#recent").getBoundingClientRect().height > target + 4; n--) renderRecent(rows, n);
}

/* ---------- Pessoas ---------- */
const PENCIL = '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/></svg>';
function personCard(p, days) {
  if (S.editing === p.id) return personForm(p);
  const apps = (p.apps || []).filter((a) => a.minutes || a.queries).slice(0, 3).map((a) => esc(a.app)).join(", ");
  const facts = [
    [t("pp.work"), mins(p.work_minutes)],
    [t("pp.routine"), p.start ? `${p.start} – ${p.end}` : "—"],
    p.home_s != null ? [t("pp.home"), WH.secs(p.home_s)] : [t("pp.night"), mins(p.night_minutes)],
  ];
  if (apps) facts.push([t("pp.apps"), apps]);
  return `<div class="card person">
    <div class="p-head">${WH.avatar(p.name)}<b>${esc(p.name)}</b>
      <button class="icon-btn sm" data-edit="${p.id}" title="${esc(t("pp.edit"))}" aria-label="${esc(t("pp.edit"))}">${PENCIL}</button></div>
    <div class="p-num">${mins(p.minutes)}${days > 1 && p.days_active ? `<small>${esc(t("pp.perDay", { v: mins(p.per_day) }))}</small>` : ""}</div>
    ${WH.catStrip(p.categories)}
    ${p.titles.length ? `<div class="titles">${p.titles.slice(0, 3).map(WH.titleChip).join("")}</div>` : ""}
    <dl class="facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>
  </div>`;
}
function personForm(p) {
  return `<div class="card person"><form class="p-edit" data-form="${p ? p.id : "new"}">
    <input name="name" maxlength="30" value="${p ? esc(p.name) : ""}" placeholder="${esc(t("pp.name"))}" autocomplete="off">
    <button class="btn primary sm" type="submit">${esc(t("edit.save"))}</button>
    ${p ? `<button class="btn sm" type="button" data-del="${p.id}">${esc(t("pp.delete"))}</button>` : ""}
    <button class="btn sm" type="button" data-cancel>${esc(t("edit.cancel"))}</button>
  </form></div>`;
}
function renderPeople(x) {
  S.people = x;
  const days = x.days.length;
  $("#pp-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const cards = x.people.map((p) => personCard(p, days));
  cards.push(S.editing === "new" ? personForm(null) : `<button class="add-card" data-add>+ ${esc(t("pp.add"))}</button>`);
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
  if (b.dataset.add !== undefined) { S.editing = "new"; return renderPeople(S.people); }
  if (b.dataset.edit) { S.editing = Number(b.dataset.edit); return renderPeople(S.people); }
  if (b.dataset.cancel !== undefined) { S.editing = null; return renderPeople(S.people); }
  if (b.dataset.del && confirm(t("pp.confirmDelete"))) {
    await WH.post("/api/person", { id: Number(b.dataset.del), delete: true });
    S.editing = null;
    load();
  }
});
$("#people").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, name = f.elements.name.value.trim();
  if (!name) return;
  const r = await WH.post("/api/person", { id: f.dataset.form === "new" ? null : Number(f.dataset.form), name });
  if (r.ok) { S.editing = null; load(); }
});

/* ---------- Aparelhos ---------- */
function renderDevices() {
  let list = S.devices.slice();
  if (S.filter === "online") list = list.filter((d) => d.online);
  if (S.filter === "offline") list = list.filter((d) => !d.online);
  if (S.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, WH.locale));
  else if (S.sort === "recent") list.sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0));
  else list.sort((a, b) => (a.hidden - b.hidden) || (b.online - a.online) || (b.today_minutes - a.today_minutes) || ((b.last_seen || 0) - (a.last_seen || 0)));
  const counted = S.devices.filter((d) => !d.hidden);
  $("#dev-desc").textContent = t("dev.desc", { n: counted.length, on: counted.filter((d) => d.online).length });
  renderTodo(S.devices);
  if (!list.length) { setHTML($("#devices"), `<div class="card empty"><b>${esc(t("dev.none"))}</b>${esc(t("dev.noneHint"))}</div>`); return; }
  const now = Date.now() / 1000;
  // grupos: cada pessoa (em ordem alfabética), sem dono e infraestrutura
  const owners = [...new Set(list.filter((d) => !d.hidden && d.person).map((d) => d.person))].sort((a, b) => a.localeCompare(b, WH.locale));
  const groups = owners.map((o) => [`${WH.avatar(o, "sm")}${esc(o)}`, list.filter((d) => !d.hidden && d.person === o)]);
  groups.push([esc(owners.length ? t("dev.groupNone") : t("dev.title")), list.filter((d) => !d.hidden && !d.person)]);
  groups.push([esc(t("dev.groupInfra")), list.filter((d) => d.hidden)]);
  const card = (d) => {
    const state = d.online ? t("dev.isOnline") : t("dev.seen", { ago: WH.ago(d.last_seen, now) });
    const badges = (d.members && d.members.length ? ` <span class="badge" data-tip="${esc(t("dev.linksHint", { n: d.members.length + 1 }))}">+${d.members.length}</span>` : "") +
      (d.hidden ? ` <span class="badge">${esc(t("dev.infra"))}</span>` : !d.nickname ? ` <span class="badge warn">${esc(t("dev.noName"))}</span>` : "");
    return `<a class="card dev${d.online ? "" : " off"}${d.hidden ? " infra" : ""}" href="${devHref(d.mac)}">
      <span class="dev-ic">${WH.kindIcon(d.kind)}</span>
      <span class="dev-main"><b>${esc(d.name)}</b><small><span class="dot${d.online ? " on" : ""}"></span>${esc(state)} · ${esc(d.ip || "")}${badges}</small></span>
      <span class="dev-use"><b>${d.hidden ? "" : mins(d.today_minutes)}</b></span>
    </a>`;
  };
  setHTML($("#devices"), groups.filter(([, items]) => items.length).map(([title, items]) =>
    `<div class="dev-group"><div class="dev-group-h">${title}<small>${items.length}</small></div><div class="devices">${items.map(card).join("")}</div></div>`).join(""));
}

/* ---------- Relatório ---------- */
function appsHTML(apps) {
  const byMin = (apps || []).some((a) => a.minutes);
  const val = (a) => (byMin ? a.minutes : a.queries);
  const rows = (apps || []).filter(val).slice(0, 8);
  return rows.length ? WH.barsHTML(rows.map((a) => ({ label: a.app, value: val(a), color: "var(--accent-2)" })), byMin ? mins : num)
    : `<div class="empty">${esc(t("empty.period"))}</div>`;
}
function domainList(rows, field) {
  if (!rows.length) return `<div class="empty">${esc(t(field === "blocked" ? "rep.blockedNone" : "empty.period"))}</div>`;
  const max = Math.max(1, ...rows.map((r) => r[field]));
  return `<div class="dlist">${rows.map((r) => `<div class="drow">
    <span class="d-name"><b>${esc(r.domain)}</b>${WH.catChip(r.cat)}</span>
    <span class="num">${num(r[field])}</span>
    <span class="bar-t"><i style="width:${(r[field] / max) * 100}%;background:${field === "blocked" ? "var(--down)" : WH.cat(r.cat).color}"></i></span>
  </div>`).join("")}</div>`;
}
function renderReport(o) {
  const tot = o.totals, days = o.days.length;
  $("#rep-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const kpis = [
    [t("kpi.minutes"), mins(tot.minutes), t("kpi.minutesSub", { n: tot.active_devices }), "var(--accent)"],
    [t("kpi.queries"), num(tot.queries), t("kpi.queriesSub", { n: num(Math.round(tot.queries / days)) }), "var(--ok)"],
    [t("kpi.blocked"), num(tot.blocked), t("kpi.blockedSub", { p: WH.pct(tot.blocked, tot.queries) }), "var(--down)"],
    [t("kpi.new"), num(tot.new_devices), t("kpi.newSub"), "var(--warn)"],
  ];
  setHTML($("#kpis"), kpis.map(([l, v, s, c]) => `<div class="card kpi" data-tip="${esc(s)}"><h3><i style="--c:${c}"></i>${esc(l)}</h3><b>${v}</b></div>`).join(""));
  setHTML($("#usage"), WH.barsHTML(o.usage.slice(0, 10).map((u) => ({ label: u.name, value: u.minutes, icon: `<span class="mini-ic">${WH.kindIcon(u.kind)}</span>`, href: devHref(u.mac) })), mins));
  setHTML($("#cats"), WH.catsHTML(o.categories));
  setHTML($("#hours"), WH.hoursHTML(o.hours));
  setHTML($("#apps"), appsHTML(o.apps));
  setHTML($("#sites"), domainList(o.top_domains.slice(0, 10), "queries"));
  setHTML($("#blocked"), domainList(o.blocked, "blocked"));
  $("#night-title").textContent = t("rep.nightTitle", { a: o.night_from, b: o.night_to });
  setHTML($("#night"), o.night.length ? WH.barsHTML(o.night.map((u) => ({ label: u.name, value: u.minutes, icon: `<span class="mini-ic">${WH.kindIcon(u.kind)}</span>`, href: devHref(u.mac), color: "var(--accent-2)" })), mins)
    : `<div class="empty">${esc(t("rep.nightNone"))}</div>`);
}

/* ---------- Ajustes ---------- */
function renderSettings(c) {
  $("#ntfy-desc").textContent = c.ntfy ? t("ntfy.on") : t("ntfy.off");
  $("#test").hidden = !c.ntfy;
  const facts = [[t("set.version"), c.version], [t("set.address"), `${c.host || c.ip}:${c.port}`], [t("set.adguard"), c.adguard_url]];
  setHTML($("#about"), facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v || "—")}</dd>`).join(""));
}
WH.mountLangSeg($("#lang-seg"));
WH.mountThemeSeg($("#theme-seg"), $("#theme-hint"));
$("#test").onclick = async () => {
  const r = await WH.post("/api/test-notify");
  const res = $("#test-res");
  res.className = "res " + (r.ok ? "ok" : "bad");
  res.textContent = r.ok ? t("ntfy.sent") : t("ntfy.err." + (r.code || "send_failed"), { s: r.wait || "" });
};

/* ---------- carga (só o que a aba aberta mostra) ---------- */
async function load() {
  $("#refresh").classList.add("spin");
  try {
    const net = WH.get("/api/internet").then(renderNet).catch(() => {});
    if (S.tab === "now") {
      const [n, today, ins, act, p] = await Promise.all([WH.get("/api/now"), WH.get("/api/overview?period=today"), WH.get("/api/insights"),
        WH.get("/api/activity"), WH.get("/api/people?period=today")]);
      renderNow(n, today, p); renderInsights(ins); fitRecent(act);
    } else if (S.tab === "people") {
      const p = await WH.get("/api/people?period=" + S.period);
      if (S.editing === null) renderPeople(p); else S.people = p;
    } else if (S.tab === "devices") {
      S.devices = await WH.get("/api/devices");
      renderDevices();
    } else if (S.tab === "report") {
      renderReport(await WH.get("/api/overview?period=" + S.period));
    } else if (S.tab === "settings") {
      S.cfg = S.cfg || await WH.get("/api/config");
      renderSettings(S.cfg);
    }
    await net;
  } catch (e) {
    $("#foot").textContent = t("err.load");
  } finally {
    $("#refresh").classList.remove("spin");
  }
}

WH.seg($("#dev-filter"), S.filter, (v) => { S.filter = v; WH.store.set("filter", v); renderDevices(); });
WH.seg($("#period-seg"), S.period, (v) => { S.period = v; WH.store.set("period", v); load(); });
$("#dev-sort").value = S.sort;
$("#dev-sort").onchange = (e) => { S.sort = e.target.value; WH.store.set("sort", S.sort); renderDevices(); };
$("#refresh").onclick = load;

showTab(location.hash.slice(1));
setInterval(() => { if (!document.hidden && S.editing === null) load(); }, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

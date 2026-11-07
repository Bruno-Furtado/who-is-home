"use strict";
// Página de um aparelho: presença, uso, horários, categorias e sites.
const { t, $, esc, mins, num } = WH;
WH.applyStatic();
WH.markTab("devices");
WH.initTips();

const mac = new URLSearchParams(location.search).get("mac") || "";
let period = WH.store.get("dperiod", "7d");
let dev = null;
let detail = null;

function renderHead(d) {
  dev = d;
  document.title = d.name + " · who-is-home";
  $("#d-ic").innerHTML = WH.kindIcon(d.kind);
  $("#d-name").textContent = d.name;
  const now = Date.now() / 1000;
  const chips = [
    d.online ? `<span class="chip-s ok"><span class="dot on"></span>${esc(t("dev.isOnline"))}</span>`
      : `<span class="chip-s"><span class="dot"></span>${esc(t("dev.seen", { ago: WH.ago(d.last_seen, now) }))}</span>`,
    `<span class="chip-s" data-tip="${esc(t("d.ipHint"))}">IP ${esc(d.ip || "—")}</span>`,
    `<span class="chip-s mono" data-tip="${esc(t("d.macHint"))}">${esc(d.mac)}</span>`,
  ];
  if (d.person) chips.unshift(`<span class="chip-s">${WH.avatar(d.person, "sm")}${esc(d.person)}</span>`);
  if (d.hidden) chips.push(`<span class="chip-s" data-tip="${esc(t("dev.infraHint"))}">${esc(t("dev.infra"))}</span>`);
  else if (d.private_mac) chips.push(`<span class="chip-s warn" data-tip="${esc(t("dev.privateHint"))}">${esc(t("dev.private"))}</span>`);
  if (d.hostname && d.hostname !== d.name) chips.push(`<span class="chip-s" data-tip="${esc(t("d.hostHint", { src: t("src." + (d.name_source || "mdns")) }))}">${esc(d.hostname)}</span>`);
  chips.push(`<span class="chip-s">${esc(t("d.first", { date: WH.date(d.first_seen) }))}</span>`);
  $("#d-chips").innerHTML = chips.join("");
  // MACs juntados a este aparelho (cabo e Wi-Fi, MAC privado antigo): cada um pode ser separado de novo
  const box = $("#d-members");
  box.hidden = !d.members.length;
  box.innerHTML = d.members.map((m) => `<span class="chip-s mono">${m.online ? '<span class="dot on"></span>' : ""}${esc(m.mac)} · ${esc(m.ip || "")}
    <button class="btn sm" data-split="${esc(m.mac)}">${esc(t("d.split"))}</button></span>`).join("");
}
$("#d-members").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-split]");
  if (!b) return;
  await WH.post("/api/device", { mac: b.dataset.split, parent: null });
  load();
});

function timelineHTML(days, now) {
  const ticks = [0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}h</span>`).join("");
  const rows = days.slice().reverse().map((d) => {
    const span = d.end - d.start, P = (x) => ((x - d.start) / span) * 100;
    let segs = d.online.map(([a, b]) => `<i class="s-mon" style="left:${P(a)}%;width:${Math.max(0.3, P(b) - P(a))}%" data-tip="${esc(t("d.onlineTip", { a: WH.time(a), b: WH.time(b), dur: WH.secs(b - a) }))}"></i>`).join("");
    segs += d.active.map(([a, b]) => `<i class="s-act" style="left:${P(a)}%;width:${Math.max(0.25, P(b) - P(a))}%" data-tip="${esc(t("d.activeTip", { a: WH.time(a), b: WH.time(b), dur: mins((b - a) / 60) }))}"></i>`).join("");
    if (now < d.end) segs += `<i class="s-fut" style="left:${P(Math.max(now, d.start))}%;right:0"></i>`;
    return `<div class="tl-row"><div class="tl-day">${esc(WH.dayLabel(d.start))}</div><div class="tl-track">${segs}</div>
      <div class="tl-meta"><b>${mins(d.minutes)}</b><span>${esc(WH.secs(d.online_s))}</span></div></div>`;
  }).join("");
  return `<div class="tl"><div class="tl-row tl-axis"><div></div><div class="tl-ticks">${ticks}</div><div class="tl-meta"><span>${esc(t("d.tlHeader"))}</span></div></div>${rows}</div>`;
}

function domainTable(rows, field) {
  if (!rows.length) return `<div class="empty">${esc(t(field === "blocked" ? "rep.blockedNone" : "empty.period"))}</div>`;
  const max = Math.max(1, ...rows.map((r) => r[field]));
  return `<div class="dlist">${rows.map((r) => `<div class="drow">
    <span class="d-name"><b>${esc(r.domain)}</b>${WH.catChip(r.cat)}</span>
    <span class="num">${num(r[field])}${field === "queries" && r.blocked ? `<small class="bad">${esc(t("d.blockedN", { n: num(r.blocked) }))}</small>` : ""}</span>
    <span class="bar-t"><i style="width:${(r[field] / max) * 100}%;background:${field === "blocked" ? "var(--down)" : WH.cat(r.cat).color}"></i></span>
  </div>`).join("")}</div>`;
}

function render(x) {
  detail = x;
  renderHead(x.device);
  const tot = x.totals, days = x.days.length;
  $("#d-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const kpis = [
    [t("kpi.minutes"), mins(tot.minutes), days > 1 ? t("d.perDay", { v: mins(tot.minutes / days) }) : t("d.minutesSub"), "var(--accent)"],
    [t("d.online"), WH.secs(tot.online_s), t("d.onlineSub"), "var(--ok)"],
    [t("kpi.queries"), num(tot.queries), t("d.queriesSub"), "var(--accent-2)"],
    [t("kpi.blocked"), num(tot.blocked), t("kpi.blockedSub", { p: WH.pct(tot.blocked, tot.queries) }), "var(--down)"],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v, s, c]) => `<div class="card kpi" data-tip="${esc(s)}"><h3><i style="--c:${c}"></i>${esc(l)}</h3><b>${v}</b></div>`).join("");
  $("#timeline").innerHTML = timelineHTML(x.days, x.now);
  $("#hours").innerHTML = WH.hoursHTML(x.hours);
  $("#cats").innerHTML = WH.catsHTML(x.categories);
  const byMin = x.apps.some((a) => a.minutes);
  const appVal = (a) => (byMin ? a.minutes : a.queries);
  $("#apps").innerHTML = x.apps.filter(appVal).length ? WH.barsHTML(x.apps.filter(appVal).map((a) => ({ label: a.app, value: appVal(a), color: "var(--accent-2)" })), byMin ? mins : num)
    : `<div class="empty">${esc(t("empty.period"))}</div>`;
  $("#sites").innerHTML = domainTable(x.domains, "queries");
  $("#blocked").innerHTML = domainTable(x.blocked, "blocked");
}

async function load() {
  try { render(await WH.get(`/api/device?mac=${encodeURIComponent(mac)}&period=${period}`)); }
  catch (e) {
    $("#d-name").textContent = t("d.notFound");
    $("#edit").hidden = true;
  }
}

/* ---------- editar nome e tipo ---------- */
$("#e-kind").innerHTML = `<option value="">${esc(t("kind.auto"))}</option>` + WH.KINDS.map((k) => `<option value="${k}">${esc(t("kind." + k))}</option>`).join("");
$("#edit").onclick = () => {
  if (!dev) return;
  $("#e-name").value = dev.nickname || "";
  $("#e-name").placeholder = dev.hostname || dev.ip || "";
  $("#e-kind").value = dev.kind || "";
  $("#e-person").innerHTML = `<option value="">${esc(t("edit.nobody"))}</option>` +
    detail.people.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("") + `<option value="new">${esc(t("edit.newPerson"))}</option>`;
  $("#e-person").value = dev.person_id && detail.people.some((p) => p.id === dev.person_id) ? String(dev.person_id) : "";
  $("#e-join").innerHTML = `<option value="">${esc(t("edit.noJoin"))}</option>` +
    detail.candidates.map((c) => `<option value="${esc(c.mac)}">${esc(c.name)}</option>`).join("");
  $("#e-join").value = "";
  $("#e-hidden").checked = !!dev.hidden;
  $("#e-new-wrap").hidden = true;
  $("#edit-form").hidden = false;
  $("#edit").hidden = true;
  $("#e-name").focus();
};
$("#e-cancel").onclick = () => { $("#edit-form").hidden = true; $("#edit").hidden = false; $("#e-res").textContent = ""; };
$("#edit-form").onsubmit = async (e) => {
  e.preventDefault();
  let person = $("#e-person").value;
  if (person === "new") {
    const name = $("#e-new").value.trim();
    const p = name ? await WH.post("/api/person", { name }) : { ok: false };
    if (!p.ok) { $("#e-res").className = "res bad"; $("#e-res").textContent = t("edit.error"); return; }
    person = p.id;
  }
  const body = { mac: dev.mac, nickname: $("#e-name").value, kind: $("#e-kind").value || null,
    person_id: person ? Number(person) : null, hidden: $("#e-hidden").checked };
  if ($("#e-join").value) body.parent = $("#e-join").value;
  const r = await WH.post("/api/device", body);
  if (r.ok && body.parent) { location.href = "/device?mac=" + encodeURIComponent(body.parent); return; }
  if (r.ok) { $("#edit-form").hidden = true; $("#edit").hidden = false; $("#e-res").textContent = ""; load(); }
  else { $("#e-res").className = "res bad"; $("#e-res").textContent = t("edit.error"); }
};

$("#e-person").onchange = () => { $("#e-new-wrap").hidden = $("#e-person").value !== "new"; if ($("#e-person").value === "new") $("#e-new").focus(); };

WH.seg($("#period-seg"), period, (v) => { period = v; WH.store.set("dperiod", v); load(); });
load();
setInterval(() => { if (!document.hidden && $("#edit-form").hidden) load(); }, 60000);

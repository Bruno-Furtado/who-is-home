"use strict";
// Página de uma pessoa: quando esteve em uso e em casa, dia a dia, somando todos os aparelhos dela.
const { t, $, esc, mins, num } = WH;
WH.applyStatic();
WH.markTab("people");
WH.initTips();

const id = Number(new URLSearchParams(location.search).get("id")) || 0;
let period = WH.store.get("pperiod", "7d");
const devHref = (mac) => "/device?mac=" + encodeURIComponent(mac);

function render(x) {
  const p = x.person, s = x.summary, tot = x.totals, days = x.days.length;
  document.title = p.name + " · who-is-home";
  $("#p-av").innerHTML = WH.avatar(p.name, "lg");
  $("#p-name").textContent = p.name;
  $("#p-titles").innerHTML = s.titles.map(WH.titleChip).join("");
  $("#p-devices").innerHTML = x.devices.map((d) =>
    `<a class="chip-s" href="${devHref(d.mac)}">${d.online ? '<span class="dot on"></span>' : ""}${esc(d.name)}</a>`).join("");
  $("#p-desc").textContent = days === 1 ? t("rep.descToday") : t("rep.descDays", { n: days });
  const kpis = [
    [t("kpi.minutes"), mins(tot.minutes), days > 1 ? t("d.perDay", { v: mins(s.per_day) }) : t("d.minutesSub"), "var(--accent)"],
    x.has_home ? [t("pp.home"), WH.secs(tot.online_s), t("pp.homeHint"), "var(--ok)"] : [t("pp.night"), mins(s.night_minutes), t("pp.nightHint"), "var(--accent-2)"],
    [t("pp.work"), mins(s.work_minutes), s.work_start ? t("pp.workHint", { a: s.work_start, b: s.work_end }) : t("pp.work"), "var(--c-work)"],
    [t("pp.routine"), s.start ? `${s.start}–${s.end}` : "—", t("pp.routineHint"), "var(--warn)"],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v, tip, c]) => `<div class="card kpi" data-tip="${esc(tip)}"><h3><i style="--c:${c}"></i>${esc(l)}</h3><b>${v}</b></div>`).join("");
  $("#leg-home").hidden = !x.has_home;
  $("#timeline").innerHTML = WH.timelineHTML(x.days, x.now);
  $("#hours").innerHTML = WH.hoursHTML(x.hours);
  $("#cats").innerHTML = WH.catsHTML(x.categories);
  const byMin = x.apps.some((a) => a.minutes);
  const val = (a) => (byMin ? a.minutes : a.queries);
  const apps = x.apps.filter(val);
  $("#apps").innerHTML = apps.length ? WH.barsHTML(apps.map((a) => ({ label: a.app, value: val(a), color: "var(--accent-2)" })), byMin ? mins : num)
    : `<div class="empty">${esc(t("empty.period"))}</div>`;
  $("#sites").innerHTML = x.domains.length ? WH.barsHTML(x.domains.map((r) => ({ label: r.domain, value: r.queries, color: WH.cat(r.cat).color })), num)
    : `<div class="empty">${esc(t("empty.period"))}</div>`;
}

async function load() {
  try { render(await WH.get(`/api/person?id=${id}&period=${period}`)); }
  catch (e) { $("#p-name").textContent = t("pr.notFound"); }
}

WH.seg($("#period-seg"), period, (v) => { period = v; WH.store.set("pperiod", v); load(); });
load();
setInterval(() => { if (!document.hidden) load(); }, 60000);

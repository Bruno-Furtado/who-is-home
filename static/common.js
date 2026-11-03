"use strict";
// Utilitários compartilhados pelo painel e pela página do aparelho (depende de i18n.js).
const WH = (() => {
  const store = {
    get(k, d) { try { const v = localStorage.getItem("wh_" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("wh_" + k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
  };
  const $ = (s, root) => (root || document).querySelector(s);

  /* ---------- idioma ---------- */
  const LANGS = [
    { code: "en", name: "English", locale: "en-US" },
    { code: "pt", name: "Português", locale: "pt-BR" },
    { code: "zh", name: "中文", locale: "zh-CN" },
  ];
  function detectLang() {
    const saved = store.get("lang", null);
    if (saved && I18N[saved]) return saved;
    for (const l of navigator.languages || [navigator.language || "en"]) {
      const code = String(l).slice(0, 2).toLowerCase();
      if (I18N[code]) return code;
    }
    return "en";
  }
  const lang = detectLang();
  const locale = LANGS.find((l) => l.code === lang).locale;
  document.documentElement.lang = locale;

  function t(key, vars) {
    let s = (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;
    if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  }

  // Bandeiras em SVG: emoji de bandeira não aparece no Windows.
  function star(cx, cy, r, rot) {
    const p = [];
    for (let i = 0; i < 10; i++) {
      const a = rot + (Math.PI / 5) * i - Math.PI / 2, rr = i % 2 ? r * 0.38 : r;
      p.push((cx + rr * Math.cos(a)).toFixed(2) + "," + (cy + rr * Math.sin(a)).toFixed(2));
    }
    return `<polygon points="${p.join(" ")}" fill="#ffde00"/>`;
  }
  const FLAGS = {
    en: () => {
      let s = `<rect width="30" height="20" fill="#fff"/>`;
      for (let i = 0; i < 7; i++) s += `<rect y="${(i * 40) / 13}" width="30" height="${20 / 13}" fill="#b22234"/>`;
      s += `<rect width="13" height="${(20 * 7) / 13}" fill="#3c3b6e"/>`;
      for (let r = 0; r < 4; r++) for (let c = 0; c < 5; c++) s += `<circle cx="${1.5 + c * 2.5}" cy="${1.4 + r * 2.5}" r=".55" fill="#fff"/>`;
      return s;
    },
    pt: () => `<rect width="30" height="20" fill="#009c3b"/><polygon points="15,2.2 27.6,10 15,17.8 2.4,10" fill="#ffdf00"/><circle cx="15" cy="10" r="4.4" fill="#002776"/><path d="M10.8 9.2a9 9 0 0 1 8.5 1.6" stroke="#fff" stroke-width=".8" fill="none"/>`,
    zh: () => `<rect width="30" height="20" fill="#de2910"/>${star(5, 5, 3, 0)}${star(10, 2, 1, 0.9)}${star(12, 4, 1, 0.6)}${star(12, 7, 1, 0)}${star(10, 9, 1, 0.9)}`,
  };
  const flag = (code) => `<svg class="flag" viewBox="0 0 30 20" aria-hidden="true">${FLAGS[code]()}</svg>`;

  // Preenche textos estáticos: data-i18n (texto), data-i18n-html (HTML do próprio dicionário), data-i18n-title.
  function applyStatic(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    (root || document).querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    (root || document).querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
      el.setAttribute("aria-label", el.title);
    });
  }

  function closeMenus(except) { document.querySelectorAll(".menu.on").forEach((m) => m !== except && m.classList.remove("on")); }

  // Botão + menu de idioma; trocar recarrega a página (todos os textos e formatos mudam juntos).
  function mountLangMenu(btn, menu) {
    btn.innerHTML = flag(lang);
    btn.title = t("lang");
    btn.setAttribute("aria-label", t("lang"));
    menu.innerHTML = LANGS.map((l) => `<button role="menuitemradio" aria-checked="${l.code === lang}" data-v="${l.code}" class="${l.code === lang ? "on" : ""}">` +
      `${flag(l.code)}<span>${l.name}</span><span>${l.code === lang ? "✓" : ""}</span></button>`).join("");
    const toggle = (open) => { menu.classList.toggle("on", open); btn.setAttribute("aria-expanded", open); };
    btn.addEventListener("click", (e) => { e.stopPropagation(); closeMenus(menu); toggle(!menu.classList.contains("on")); });
    menu.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.v !== lang) { store.set("lang", b.dataset.v); location.reload(); } else toggle(false);
    });
    document.addEventListener("click", () => toggle(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
  }

  /* ---------- tema (igual ao down-again: escuro à noite por padrão) ---------- */
  const DARK_FROM = 19, DARK_TO = 7;
  const THEME_ICONS = {
    hour: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    system: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    dark: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  };
  const svgIcon = (k) => `<svg viewBox="0 0 24 24">${THEME_ICONS[k]}</svg>`;
  function mountThemeMenu(btn, menu) {
    const THEMES = [
      ["hour", t("theme.hour"), t("theme.hourHint", { a: DARK_FROM, b: DARK_TO })],
      ["system", t("theme.system"), t("theme.systemHint")],
      ["light", t("theme.light"), ""],
      ["dark", t("theme.dark"), ""],
    ];
    let theme = store.get("theme", "hour");
    function apply() {
      let th = theme;
      if (th === "hour") { const h = new Date().getHours(); th = h >= DARK_FROM || h < DARK_TO ? "dark" : "light"; }
      if (th === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = th;
      const shown = th === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : th;
      btn.innerHTML = svgIcon(theme === "hour" || theme === "system" ? theme : shown);
      btn.title = t("theme");
      btn.setAttribute("aria-label", t("theme"));
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = shown === "dark" ? "#080c15" : "#f2f4f9";
      menu.innerHTML = THEMES.map(([k, l, h]) =>
        `<button role="menuitemradio" aria-checked="${k === theme}" data-v="${k}" class="${k === theme ? "on" : ""}">${svgIcon(k)}<span>${l}${h ? `<small>${h}</small>` : ""}</span><span>${k === theme ? "✓" : ""}</span></button>`).join("");
    }
    const toggle = (open) => { menu.classList.toggle("on", open); btn.setAttribute("aria-expanded", open); };
    btn.addEventListener("click", (e) => { e.stopPropagation(); closeMenus(menu); toggle(!menu.classList.contains("on")); });
    menu.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      theme = b.dataset.v; store.set("theme", theme); apply(); toggle(false);
    });
    document.addEventListener("click", () => toggle(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
    apply();
    setInterval(apply, 60000);
  }

  /* ---------- formatação ---------- */
  const pad = (n) => String(n).padStart(2, "0");
  const D = (ts) => new Date(ts * 1000);
  const U = { d: t("unit.d"), h: t("unit.h"), min: t("unit.min") };
  // minutos → "2h05" / "35 min"
  function mins(m) {
    if (m == null) return "—";
    m = Math.round(m);
    const h = Math.floor(m / 60);
    return h ? `${h}${U.h}${pad(m % 60)}` : `${m} ${U.min}`;
  }
  const secs = (s) => mins((s || 0) / 60);
  // "há 5 min", "há 3 h", "há 2 d"
  function ago(ts, now) {
    const s = Math.max(0, (now || Date.now() / 1000) - ts);
    if (s < 90) return t("ago.now");
    if (s < 3600) return t("ago.min", { n: Math.round(s / 60) });
    if (s < 86400 * 2) return t("ago.h", { n: Math.round(s / 3600) });
    return t("ago.d", { n: Math.round(s / 86400) });
  }
  const fmt = (opts) => new Intl.DateTimeFormat(locale, opts);
  const F_DAY = fmt({ weekday: "short", day: "2-digit", month: "2-digit" });
  const F_DATE = fmt({ day: "2-digit", month: "2-digit", year: "numeric" });
  const time = (ts) => { const d = D(ts); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const dayLabel = (ts) => F_DAY.format(D(ts));
  const date = (ts) => F_DATE.format(D(ts));
  const dt = (ts) => `${dayLabel(ts)} · ${time(ts)}`;
  const num = (x) => (x == null ? "—" : Number(x).toLocaleString(locale));
  const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : 0);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function get(url, opts) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opts));
    if (!r.ok) throw new Error(r.status + "");
    return r.json();
  }
  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Who-Is-Home": "1" }, body: JSON.stringify(body || {}) });
    return r.json().catch(() => ({ ok: false }));
  }

  /* ---------- aparelhos e categorias ---------- */
  const KIND_ICONS = {
    phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    tablet: '<rect x="4.5" y="2.5" width="15" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    computer: '<rect x="4" y="5" width="16" height="11" rx="2"/><path d="M2 19h20"/>',
    tv: '<rect x="2.5" y="4.5" width="19" height="12.5" rx="2"/><path d="M8 20.5h8"/>',
    console: '<path d="M7 9h10a4 4 0 0 1 4 4v1.5a2.5 2.5 0 0 1-4.6 1.4L15.5 14h-7l-.9 1.9A2.5 2.5 0 0 1 3 14.5V13a4 4 0 0 1 4-4z"/><path d="M8 11.5v2M7 12.5h2M15.5 12h.01M17 13.5h.01"/>',
    watch: '<rect x="6.5" y="6" width="11" height="12" rx="3"/><path d="M9 6l.6-3h4.8l.6 3M9 18l.6 3h4.8l.6-3"/>',
    speaker: '<rect x="6" y="2.5" width="12" height="19" rx="3"/><circle cx="12" cy="14" r="3.2"/><path d="M12 7h.01"/>',
    printer: '<path d="M7 8V3h10v5"/><rect x="3" y="8" width="18" height="9" rx="2"/><path d="M7 14h10v7H7z"/>',
    camera: '<rect x="3" y="6.5" width="13" height="11" rx="2"/><path d="M16 10.5l5-3v9l-5-3"/>',
    router: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 16.5h.01M11 16.5h.01M8 9a5.5 5.5 0 0 1 8 0M5.5 6.5a9 9 0 0 1 13 0"/>',
    other: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
  };
  const kindIcon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${KIND_ICONS[k] || KIND_ICONS.other}</svg>`;
  const CAT_COLORS = {
    social: "var(--c-social)", video: "var(--c-video)", music: "var(--c-music)", games: "var(--c-games)",
    messaging: "var(--c-messaging)", shopping: "var(--c-shopping)", news: "var(--c-news)", work: "var(--c-work)",
    search: "var(--c-search)", system: "var(--c-system)", ads: "var(--c-ads)", other: "var(--c-other)",
  };
  const cat = (c) => ({ code: c || "other", label: t("cat." + (CAT_COLORS[c] ? c : "other")), color: CAT_COLORS[c] || CAT_COLORS.other });
  const catChip = (c) => { const x = cat(c); return `<span class="cat" style="--c:${x.color}"><i></i>${esc(x.label)}</span>`; };

  // Barras por hora (24 colunas), valores em minutos de uso.
  function hoursHTML(hours) {
    const max = Math.max(1, ...hours);
    const peak = hours.indexOf(Math.max(...hours));
    return `<div class="hbars">${hours.map((v, h) => {
      const tip = t("hours.tip", { range: `${pad(h)}h–${pad((h + 1) % 24)}h`, time: mins(v) });
      return `<div class="hb${v && h === peak ? " peak" : ""}" data-tip="${esc(tip)}"><i style="height:${v ? Math.max(4, (v / max) * 100) : 0}%"></i><span>${h % 3 === 0 ? h + "h" : ""}</span></div>`;
    }).join("")}</div>`;
  }

  // Lista de barras horizontais: [{label, sub, value, color, href}]
  function barsHTML(rows, fmtValue) {
    if (!rows.length) return `<div class="empty">${esc(t("empty.period"))}</div>`;
    const max = Math.max(1, ...rows.map((r) => r.value));
    return `<div class="bars">${rows.map((r) => {
      const inner = `<span class="bar-l">${r.icon || ""}<span><b>${esc(r.label)}</b>${r.sub ? `<small>${r.sub}</small>` : ""}</span></span>
        <span class="bar-v">${fmtValue(r.value)}</span>
        <span class="bar-t"><i style="width:${Math.max(2, (r.value / max) * 100)}%;background:${r.color || "var(--accent)"}"></i></span>`;
      return r.href ? `<a class="bar" href="${esc(r.href)}">${inner}</a>` : `<div class="bar">${inner}</div>`;
    }).join("")}</div>`;
  }

  // Categorias: faixa empilhada + lista.
  function catsHTML(cats) {
    const total = cats.reduce((a, c) => a + c.minutes, 0);
    if (!total) return `<div class="empty">${esc(t("empty.period"))}</div>`;
    const stack = cats.map((c) => `<i style="width:${(c.minutes / total) * 100}%;background:${cat(c.cat).color}" data-tip="${esc(cat(c.cat).label + " · " + mins(c.minutes))}"></i>`).join("");
    const list = cats.map((c) => `<div class="crow"><i style="background:${cat(c.cat).color}"></i><span>${esc(cat(c.cat).label)}</span><span class="num">${mins(c.minutes)} <small>${pct(c.minutes, total)}%</small></span></div>`).join("");
    return `<div class="stack">${stack}</div><div class="clist">${list}</div>`;
  }

  // Tooltip único para qualquer elemento com data-tip (mouse e toque).
  function initTips() {
    const tip = document.createElement("div");
    tip.id = "tip";
    document.body.appendChild(tip);
    let cur = null;
    const place = (x, y) => {
      const r = tip.getBoundingClientRect();
      let left = x + 14, top = y + 16;
      if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
      if (top + r.height > window.innerHeight - 8) top = y - r.height - 12;
      tip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
    };
    const show = (el, x, y, html) => { cur = el; tip.innerHTML = html; tip.classList.add("on"); place(x, y); };
    const hide = () => { cur = null; tip.classList.remove("on"); };
    document.addEventListener("mousemove", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) return cur && hide();
      if (el !== cur) show(el, e.clientX, e.clientY, el.dataset.tip); else place(e.clientX, e.clientY);
    });
    document.addEventListener("touchstart", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) return hide();
      const tt = e.touches[0];
      show(el, tt.clientX, tt.clientY, el.dataset.tip);
    }, { passive: true });
    window.addEventListener("scroll", hide, { passive: true });
  }

  // Botões segmentados (período etc.).
  function seg(el, value, onPick) {
    const mark = (v) => el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
    mark(value);
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      mark(b.dataset.v);
      onPick(b.dataset.v);
    });
  }

  return { lang, locale, t, $, store, applyStatic, mountLangMenu, mountThemeMenu, mins, secs, ago, time, dayLabel, date, dt,
    num, pct, esc, get, post, kindIcon, cat, catChip, hoursHTML, barsHTML, catsHTML, initTips, seg, pad, KINDS: Object.keys(KIND_ICONS) };
})();

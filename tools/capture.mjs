// Regera as imagens de docs/ (capa, prints e GIF) a partir do painel de demonstração.
// Requer Google Chrome e ffmpeg. Sem dependências npm (usa o WebSocket nativo do Node 22+).
//
//   python3 tools/demo.py          # em outro terminal (porta 8767)
//   node tools/capture.mjs         # tudo; ou: node tools/capture.mjs shots|gif|cover
//
// Gera docs/<idioma>/{cover.png, demo.gif, dashboard.png, device.png} para en, pt e zh.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TOOLS = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(TOOLS, "..", "docs");
const WORK = path.join(os.tmpdir(), "who-is-home-capture");
const MODE = process.argv[2] || "all";
const BASE = "http://localhost:" + (process.env.PORT || "8767");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const DEVICE = "/device?mac=da:11:22:33:44:03";       // "Celular do João" da demonstração
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(DOCS, { recursive: true });
fs.mkdirSync(WORK, { recursive: true });

const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9334", `--user-data-dir=${path.join(WORK, "chrome-prof")}`,
  "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--force-color-profile=srgb", "about:blank"], { stdio: "ignore" });
let targets = [];
for (let i = 0; i < 60 && !targets.length; i++) {
  try { targets = (await (await fetch("http://127.0.0.1:9334/json/list")).json()).filter((t) => t.type === "page"); } catch (e) { /* subindo */ }
  if (!targets.length) await sleep(250);
}
const ws = new WebSocket(targets[0].webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let seq = 0;
const pending = new Map(), listeners = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
  else if (m.method) listeners.slice().forEach((l) => l(m));
};
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
const once = (name) => new Promise((r) => { const l = (m) => { if (m.method === name) { listeners.splice(listeners.indexOf(l), 1); r(m.params); } }; listeners.push(l); });
const js = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception ? r.exceptionDetails.exception.description : JSON.stringify(r.exceptionDetails));
  return r.result.value;
};
await send("Page.enable");
await send("Runtime.enable");

const viewport = (width, height, scale, mobile = false) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: scale, mobile });
async function load(url) {
  const l = once("Page.loadEventFired");
  await send("Page.navigate", { url });
  await l;
}
// abre a página com as preferências (idioma, tema, período) já gravadas no localStorage
async function go(url, prefs = {}, wait = 2000) {
  await load(url);
  await js(`(() => { localStorage.clear(); const p = ${JSON.stringify(prefs)}; for (const k in p) localStorage.setItem("wh_" + k, JSON.stringify(p[k])); })()`);
  const l = once("Page.loadEventFired");
  await send("Page.reload");
  await l;
  await sleep(wait);
}
async function shot(file, clip) {
  const r = await send("Page.captureScreenshot", Object.assign({ format: "png" }, clip ? { clip: Object.assign({ scale: 1 }, clip), captureBeyondViewport: true } : {}));
  fs.writeFileSync(file, Buffer.from(r.data, "base64"));
  console.log("ok", path.basename(file));
}
const top = (sel) => js(`document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect().top + scrollY`);

const LANGS = (process.env.LANGS || "en,pt,zh").split(",");
const PREFS = { period: "7d", dperiod: "7d" };

for (const lang of LANGS) {
  const OUT = path.join(DOCS, lang);
  fs.mkdirSync(OUT, { recursive: true });
  const prefs = (extra) => Object.assign({ lang }, PREFS, extra);
  console.log("==", lang);

  if (MODE === "all" || MODE === "shots") {
    // painel no desktop, tema escuro
    await viewport(1280, 900, 2);
    await go(BASE + "/", prefs({ theme: "dark" }));
    await shot(path.join(OUT, "dashboard.png"));

    // página do aparelho: cabeçalho, resumo e dia a dia
    await go(BASE + DEVICE, prefs({ theme: "dark" }));
    const end = await js(`(() => { const r = document.querySelector("#timeline").getBoundingClientRect(); return r.bottom + scrollY; })()`);
    await shot(path.join(OUT, "device.png"), { x: 0, y: 0, width: 1280, height: Math.ceil(end + 24) });

    // celular claro e escuro (usados na capa)
    await viewport(390, 844, 3, true);
    for (const theme of ["light", "dark"]) {
      await go(BASE + "/", prefs({ theme }));
      await shot(path.join(WORK, `mobile-${lang}-${theme}.png`));
    }
  }

  if (MODE === "all" || MODE === "gif") {
    const frames = path.join(WORK, "frames");
    fs.rmSync(frames, { recursive: true, force: true });
    fs.mkdirSync(frames);
    let n = 0;
    const frame = async () => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(frames, `f${String(n++).padStart(4, "0")}.png`), Buffer.from(r.data, "base64")); };
    const hold = async (count) => { for (let i = 0; i < count; i++) await frame(); };
    const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const scroll = async (to, steps = 16) => {
      const from = await js("scrollY");
      for (let i = 1; i <= steps; i++) { await js(`scrollTo(0, ${Math.round(from + (to - from) * ease(i / steps))})`); await frame(); }
    };

    await viewport(390, 844, 2, true);
    await go(BASE + "/", prefs({ theme: "light" }), 2500);
    await js("for (let i = 1; i < 10000; i++) clearInterval(i)");    // sem atualização automática no meio do GIF
    await hold(10);                                                    // agora + hoje
    await scroll((await top("#devices")) - 70);
    await hold(12);                                                    // aparelhos
    await scroll((await top("#usage")) - 120);
    await hold(9);                                                     // quem mais usou
    await scroll((await top("#cats")) - 120);
    await hold(8);                                                     // categorias
    await scroll((await top("#hours")) - 160);
    await hold(10);                                                    // horários
    await load(BASE + DEVICE);                                         // abre um aparelho
    await sleep(1200);
    await js("for (let i = 1; i < 10000; i++) clearInterval(i)");
    await hold(12);
    await scroll((await top("#timeline")) - 90);
    await hold(12);                                                    // dia a dia
    await scroll(0, 12);
    await js(`document.querySelector("#theme").click()`);
    await hold(6);
    await js(`document.querySelector('#theme-menu [data-v="dark"]').click()`);
    await hold(14);
    const enc = spawnSync("ffmpeg", ["-v", "error", "-y", "-framerate", "8", "-i", path.join(frames, "f%04d.png"), "-vf",
      "scale=320:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
      path.join(OUT, "demo.gif")], { stdio: "inherit" });
    console.log(enc.status === 0 ? `ok demo.gif (${n} quadros)` : "ffmpeg falhou");
  }

  if (MODE === "all" || MODE === "cover") {
    for (const theme of ["light", "dark"]) fs.copyFileSync(path.join(WORK, `mobile-${lang}-${theme}.png`), path.join(WORK, `mobile-${theme}.png`));
    fs.copyFileSync(path.join(TOOLS, "cover.html"), path.join(WORK, "cover.html"));
    await viewport(1280, 640, 2);
    await load("file://" + path.join(WORK, "cover.html") + "?lang=" + lang);
    await sleep(800);
    await shot(path.join(OUT, "cover.png"));
  }
}

ws.close();
chrome.kill();
process.exit(0);

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
who-is-home — quem está na rede de casa, quanto usa e o que acessa, com painel web.

Feito para rodar no mesmo computador ligado 24h que roda o AdGuard Home (e, de
preferência, o down-again): varre a rede para saber quem está ligado, lê o registro
de consultas do AdGuard para saber o que cada aparelho acessa e serve um painel em
http://<nome-da-maquina>.local:8080 com aparelhos, tempo de uso, categorias e alertas.

Só biblioteca padrão. Compatível com Python 3.8 (macOS 11 Big Sur).
macOS é a plataforma testada; Linux é experimental.

Uso:
  python3 who_is_home.py              roda coletor + painel (Ctrl+C para parar)
  python3 who_is_home.py setup        pede o usuário e a senha do AdGuard Home
  python3 who_is_home.py check        testa AdGuard, varredura e down-again e mostra o resultado
  python3 who_is_home.py install      inicia sozinho (macOS: LaunchAgent; Linux: systemd)
  python3 who_is_home.py uninstall    remove o início automático
"""
import argparse
import base64
import getpass
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape

VERSION = "0.1.0"
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.environ.get("WHOISHOME_DATA") or os.path.join(BASE, "dados"))   # WHOISHOME_DATA: usado pelo tools/demo.py
STATIC = os.path.join(BASE, "static")
CONFIG_PATH = os.path.join(DATA, "config.json")
DB_PATH = os.path.join(DATA, "who-is-home.db")
LOG_PATH = os.path.join(DATA, "who-is-home.log")
PLIST_LABEL = "com.whoishome.monitor"
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % PLIST_LABEL)

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
PLATFORM = "macOS" if IS_MAC else "Linux" if IS_LINUX else sys.platform

DEFAULTS = {
    "language": "auto",                       # "en", "pt", "zh" ou "auto" (idioma do sistema): avisos e terminal
    "bind": "0.0.0.0",                        # "127.0.0.1" deixa o painel só nesta máquina
    "port": 8080,
    "allowed_hosts": [],                      # nomes extras para o painel (IPs, localhost e *.local já valem)
    "adguard_url": "http://127.0.0.1:3000",   # painel do AdGuard Home
    "adguard_user": "",                       # preenchidos pelo comando setup
    "adguard_password": "",
    "poll_seconds": 15,                       # leitura do registro de consultas do AdGuard
    "scan_seconds": 60,                       # varredura da rede (ping + tabela ARP)
    "offline_minutes": 10,                    # sem sinal por N minutos = desligado (celular dormindo some do ping)
    "names_minutes": 30,                      # busca de nomes (mDNS, NetBIOS, clientes do AdGuard)
    "activity_min_queries": 2,                # consultas num minuto para contar como "em uso"
    "keep_days": 180,                         # histórico de uso e sites
    "down_again_url": "http://127.0.0.1:8000",   # "" esconde o cartão da internet
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",                         # o setup oferece usar o mesmo tópico do down-again; "" desativa
    "notify_new_devices": True,               # aviso quando um aparelho novo entra na rede
    "weekly_summary": True,                   # resumo da semana no celular
    "weekly_day": 6,                          # 0 = segunda … 6 = domingo
    "weekly_hour": 20,
    "night_from": 0,                          # "madrugada" no relatório: de night_from até night_to horas
    "night_to": 6,
    "known_devices": {},                      # {"aa:bb:cc:dd:ee:ff": {"name": "iPhone da Ana", "kind": "phone"}}: apelidos fixos por MAC
}

# Textos do servidor (avisos no celular, terminal) em todos os idiomas da interface.
# tests/test_i18n.py confere que todos os idiomas têm as mesmas chaves e os mesmos {marcadores}.
TEXTS = {
    "en": {
        "unit.h": "h", "unit.min": "min",
        "notify.new.title": "New device on the network",
        "notify.new.body": "{name} ({ip}) joined the network at {time}.",
        "notify.weekly.title": "Your network this week",
        "notify.weekly.body": "{devices} devices in use, {queries} lookups ({blocked} blocked).\nMost used: {top}.\nNew devices: {new}.",
        "notify.test.title": "who-is-home test", "notify.test.body": "If you can read this, alerts are working.",
        "notify.none": "none",
        "log.started": "who-is-home started on {os}", "log.panel": "dashboard: {url}",
        "log.stopped": "who-is-home stopped", "log.no_adguard": "AdGuard login missing: run 'python3 who_is_home.py setup'",
        "log.adguard_error": "AdGuard: {err}", "log.notify_failed": "alert not sent, retrying in 30s: {err}",
        "log.db_error": "database error: {err}", "log.new_device": "new device: {name} ({ip}, {mac})",
        "log.experimental": "warning: {os} support is experimental", "err.auth": "wrong user or password",
        "http.host": "Host not allowed. To use another name, add it to allowed_hosts in dados/config.json.",
        "setup.intro": "Connect who-is-home to AdGuard Home ({url}).",
        "setup.user": "AdGuard user: ", "setup.password": "AdGuard password (not shown): ",
        "setup.ok": "AdGuard login OK.", "setup.failed": "Could not log in to AdGuard: {err}",
        "setup.retry": "Try again? [Y/n] ",
        "setup.ntfy_reuse": "Use the same phone alerts as down-again (topic '{topic}')? [Y/n] ",
        "setup.ntfy_new": "ntfy topic for phone alerts (empty = no alerts): ",
        "setup.saved": "Saved in {path} (only your user can read it).",
        "check.adguard": "AdGuard Home", "check.scan": "Network scan", "check.down_again": "down-again",
        "check.ok": "ok", "check.failed": "failed", "check.not_set": "login missing (run setup)",
        "check.devices": "{n} devices answered", "check.queries": "ok, {n} recent lookups",
        "check.off": "not configured",
        "install.done": "Installed. who-is-home is running now and will start by itself {how}.",
        "install.panel": "Dashboard: {url}", "install.log": "Log:       {log}",
        "install.how_mac": "whenever you log in to the Mac", "install.how_linux": "when you log in",
        "install.protected": "The folder is in ~/{folder}, which macOS blocks for background programs.\nMove the who-is-home folder to your home folder (e.g. ~/who-is-home) and run this again.",
        "install.launchd_failed": "Could not load the LaunchAgent. See: launchctl load -w {path}",
        "install.no_systemd": "systemd not found. Run it in the background another way, e.g. in crontab:\n  @reboot {cmd}",
        "install.systemctl_failed": "Failed: systemctl --user {cmd}",
        "install.unsupported": "Automatic start is not supported on {os}. Run: python3 who_is_home.py",
        "uninstall.done": "Automatic start removed (your data in {data} is still there).", "uninstall.none": "It wasn't installed.",
    },
    "pt": {
        "unit.h": "h", "unit.min": "min",
        "notify.new.title": "Aparelho novo na rede",
        "notify.new.body": "{name} ({ip}) entrou na rede às {time}.",
        "notify.weekly.title": "Sua rede nesta semana",
        "notify.weekly.body": "{devices} aparelhos em uso, {queries} consultas ({blocked} bloqueadas).\nMais uso: {top}.\nAparelhos novos: {new}.",
        "notify.test.title": "Teste do who-is-home", "notify.test.body": "Se você está lendo isto, os avisos estão funcionando.",
        "notify.none": "nenhum",
        "log.started": "who-is-home iniciado no {os}", "log.panel": "painel: {url}",
        "log.stopped": "who-is-home parado", "log.no_adguard": "falta o login do AdGuard: rode 'python3 who_is_home.py setup'",
        "log.adguard_error": "AdGuard: {err}", "log.notify_failed": "aviso não enviado, tento de novo em 30s: {err}",
        "log.db_error": "erro no banco: {err}", "log.new_device": "aparelho novo: {name} ({ip}, {mac})",
        "log.experimental": "aviso: o suporte a {os} é experimental", "err.auth": "usuário ou senha errados",
        "http.host": "Host não permitido. Para usar outro nome, inclua-o em allowed_hosts no dados/config.json.",
        "setup.intro": "Conectar o who-is-home ao AdGuard Home ({url}).",
        "setup.user": "Usuário do AdGuard: ", "setup.password": "Senha do AdGuard (não aparece): ",
        "setup.ok": "Login no AdGuard OK.", "setup.failed": "Não consegui entrar no AdGuard: {err}",
        "setup.retry": "Tentar de novo? [S/n] ",
        "setup.ntfy_reuse": "Usar os mesmos avisos no celular do down-again (tópico '{topic}')? [S/n] ",
        "setup.ntfy_new": "Tópico do ntfy para avisos no celular (vazio = sem avisos): ",
        "setup.saved": "Salvo em {path} (só o seu usuário consegue ler).",
        "check.adguard": "AdGuard Home", "check.scan": "Varredura da rede", "check.down_again": "down-again",
        "check.ok": "ok", "check.failed": "falhou", "check.not_set": "falta o login (rode o setup)",
        "check.devices": "{n} aparelhos responderam", "check.queries": "ok, {n} consultas recentes",
        "check.off": "não configurado",
        "install.done": "Instalado. O who-is-home já está rodando e vai iniciar sozinho {how}.",
        "install.panel": "Painel: {url}", "install.log": "Log:    {log}",
        "install.how_mac": "sempre que você entrar no Mac", "install.how_linux": "quando você entrar no sistema",
        "install.protected": "A pasta está em ~/{folder}, que o macOS bloqueia para programas em segundo plano.\nMova a pasta who-is-home para a sua pasta pessoal (ex.: ~/who-is-home) e rode de novo.",
        "install.launchd_failed": "Falha ao carregar o LaunchAgent. Veja: launchctl load -w {path}",
        "install.no_systemd": "systemd não encontrado. Rode em segundo plano por outro meio, por exemplo no crontab:\n  @reboot {cmd}",
        "install.systemctl_failed": "Falha em: systemctl --user {cmd}",
        "install.unsupported": "Início automático não suportado em {os}. Rode: python3 who_is_home.py",
        "uninstall.done": "Início automático removido (os dados em {data} continuam lá).", "uninstall.none": "Não estava instalado.",
    },
    "zh": {
        "unit.h": "小时", "unit.min": "分",
        "notify.new.title": "网络中出现新设备",
        "notify.new.body": "{name}（{ip}）于 {time} 加入网络。",
        "notify.weekly.title": "本周网络概况",
        "notify.weekly.body": "{devices} 台设备在使用，{queries} 次查询（拦截 {blocked} 次）。\n使用最多：{top}。\n新设备：{new}。",
        "notify.test.title": "who-is-home 测试", "notify.test.body": "如果你看到这条消息，说明通知功能正常。",
        "notify.none": "无",
        "log.started": "who-is-home 已在 {os} 上启动", "log.panel": "面板：{url}",
        "log.stopped": "who-is-home 已停止", "log.no_adguard": "缺少 AdGuard 登录信息：请运行 'python3 who_is_home.py setup'",
        "log.adguard_error": "AdGuard：{err}", "log.notify_failed": "通知未发送，30 秒后重试：{err}",
        "log.db_error": "数据库错误：{err}", "log.new_device": "新设备：{name}（{ip}，{mac}）",
        "log.experimental": "提示：{os} 支持仍为实验性", "err.auth": "用户名或密码错误",
        "http.host": "不允许的 Host。如需使用其他名称，请将其加入 dados/config.json 的 allowed_hosts。",
        "setup.intro": "将 who-is-home 连接到 AdGuard Home（{url}）。",
        "setup.user": "AdGuard 用户名：", "setup.password": "AdGuard 密码（不显示）：",
        "setup.ok": "AdGuard 登录成功。", "setup.failed": "无法登录 AdGuard：{err}",
        "setup.retry": "重试？[Y/n] ",
        "setup.ntfy_reuse": "使用与 down-again 相同的手机通知（主题“{topic}”）？[Y/n] ",
        "setup.ntfy_new": "用于手机通知的 ntfy 主题（留空 = 不通知）：",
        "setup.saved": "已保存到 {path}（只有你的用户可以读取）。",
        "check.adguard": "AdGuard Home", "check.scan": "网络扫描", "check.down_again": "down-again",
        "check.ok": "正常", "check.failed": "失败", "check.not_set": "缺少登录信息（请运行 setup）",
        "check.devices": "{n} 台设备有响应", "check.queries": "正常，最近 {n} 次查询",
        "check.off": "未配置",
        "install.done": "已安装。who-is-home 正在运行，并会{how}自动启动。",
        "install.panel": "面板：{url}", "install.log": "日志：{log}",
        "install.how_mac": "在每次登录 Mac 时", "install.how_linux": "在你登录系统时",
        "install.protected": "文件夹位于 ~/{folder}，macOS 会阻止后台程序访问该位置。\n请把 who-is-home 文件夹移到个人目录（例如 ~/who-is-home）后重新运行。",
        "install.launchd_failed": "无法加载 LaunchAgent。请查看：launchctl load -w {path}",
        "install.no_systemd": "未找到 systemd。请用其他方式后台运行，例如在 crontab 中：\n  @reboot {cmd}",
        "install.systemctl_failed": "执行失败：systemctl --user {cmd}",
        "install.unsupported": "{os} 不支持自动启动。请运行：python3 who_is_home.py",
        "uninstall.done": "已移除自动启动（{data} 中的数据仍保留）。", "uninstall.none": "尚未安装。",
    },
}
LANG = "en"   # definido em load_config


def tr(key, lang=None, **kw):
    s = TEXTS.get(lang or LANG, TEXTS["en"]).get(key) or TEXTS["en"].get(key, key)
    return s.format(**kw) if kw else s


def detect_language():
    """Idioma do sistema: variáveis de ambiente; no macOS, AppleLocale."""
    found = [os.environ.get(v) for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    if IS_MAC:
        found.append(run_cmd(["defaults", "read", "-g", "AppleLocale"])[1])
    for value in found:
        code = (value or "").strip().lower()[:2]
        if code in TEXTS:
            return code
    return "en"


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(mac TEXT PRIMARY KEY, ip TEXT, hostname TEXT, name_source TEXT, nickname TEXT,
                                   kind TEXT, first_seen REAL, last_seen REAL, last_dns REAL, online INTEGER DEFAULT 0,
                                   names_ts REAL);
CREATE TABLE IF NOT EXISTS presence(id INTEGER PRIMARY KEY, mac TEXT, start_ts REAL, end_ts REAL);
CREATE INDEX IF NOT EXISTS presence_mac ON presence(mac, start_ts);
CREATE INDEX IF NOT EXISTS presence_end ON presence(end_ts);
CREATE TABLE IF NOT EXISTS activity(mac TEXT, minute INTEGER, cat TEXT, PRIMARY KEY(mac, minute)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS activity_minute ON activity(minute);
CREATE TABLE IF NOT EXISTS domains(day TEXT, mac TEXT, domain TEXT, cat TEXT, queries INTEGER, blocked INTEGER,
                                   PRIMARY KEY(day, mac, domain)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS hourly(day TEXT, mac TEXT, hour INTEGER, queries INTEGER, blocked INTEGER,
                                  PRIMARY KEY(day, mac, hour)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, mac TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, ts REAL, title TEXT, body TEXT, tag TEXT, sent_ts REAL);
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL);
"""
# Colunas que entraram depois da primeira versão (ALTER TABLE em bancos antigos).
COLUMNS = {
    "devices": [("person_id", "INTEGER"), ("parent", "TEXT"), ("hidden", "INTEGER DEFAULT 0")],
    "activity": [("app", "TEXT")],
}
SCHEMA_VERSION = 2
WRITE = threading.Lock()   # um escritor por vez no SQLite (coletor, nomes e painel rodam em threads)


def migrate(db):
    """Atualiza bancos antigos: colunas novas e, uma vez, o histórico com as regras novas de uso e categoria."""
    for table, cols in COLUMNS.items():
        have = {r[1] for r in db.execute("PRAGMA table_info(%s)" % table)}
        for name, decl in cols:
            if name not in have:
                db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))
    version = int(state_get(db, "schema", 1))
    if version < 2:
        # v2: categorias ampliadas, nomes internos (wpad.box) fora, "outros" deixa de contar como uso,
        # roteadores e este computador fora das somas
        for (dom,) in db.execute("SELECT DISTINCT domain FROM domains").fetchall():
            if is_local_name(dom):
                db.execute("DELETE FROM domains WHERE domain=?", (dom,))
            else:
                db.execute("UPDATE domains SET cat=? WHERE domain=?", (categorize(dom), dom))
        db.execute("DELETE FROM activity WHERE cat IN (%s)" % ",".join("?" * len(PASSIVE_CATEGORIES)), PASSIVE_CATEGORIES)
        db.execute("UPDATE devices SET hidden=1 WHERE kind='router'")
        own = own_macs()
        if own:
            db.execute("UPDATE devices SET hidden=1 WHERE mac IN (%s)" % ",".join("?" * len(own)), sorted(own))
    state_set(db, "schema", SCHEMA_VERSION)
    db.commit()


# --------------------------------------------------------------------------
# utilidades

def log(msg):
    print("[%s] %s" % (time.strftime("%d/%m %H:%M:%S"), msg), flush=True)


def fmt_minutes(m, lang=None):
    m = int(round(m))
    h, m = divmod(m, 60)
    if h:
        return "%d%s%02d" % (h, tr("unit.h", lang), m)
    return "%d %s" % (m, tr("unit.min", lang))


def day_str(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def midnight(ts):
    return datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def state_get(db, key, default=None):
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def state_set(db, key, value):
    db.execute("INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)", (key, str(value)))


def load_config():
    # dados/ guarda a senha do AdGuard e o tópico do ntfy: só o dono lê.
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    os.chmod(DATA, 0o700)
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        save_config(cfg)
    global LANG
    LANG = cfg["language"] if cfg.get("language") in TEXTS else detect_language()
    db = connect()
    db.executescript(SCHEMA)
    with WRITE:
        migrate(db)
    db.close()
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def run_cmd(args, timeout=5):
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return r.returncode, r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def local_ip():
    """IP desta máquina na rede de casa (UDP 'connect' não envia nada, só escolhe a interface)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def local_hostname():
    if IS_MAC:
        code, out = run_cmd(["scutil", "--get", "LocalHostName"])
        if code == 0 and out.strip():
            return out.strip() + ".local"
    name = socket.gethostname().split(".")[0]
    return name + ".local" if IS_LINUX else name


def fetch_json(url, timeout=4, auth=None):
    headers = {"User-Agent": "who-is-home/" + VERSION, "Accept": "application/json"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % auth).encode("utf-8")).decode("ascii")
    with urlopen(Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------
# rede: varredura (ping + tabela ARP), MAC e nomes
#
# macOS é a plataforma testada. Os leitores parse_* são funções puras, cobertas por tests/.

def norm_mac(mac):
    """'6:2:aa:bb:c:1e' (formato do arp do macOS) → '06:02:aa:bb:0c:1e'."""
    parts = re.split(r"[:-]", (mac or "").strip().lower())
    if len(parts) != 6 or not all(re.match(r"^[0-9a-f]{1,2}$", p) for p in parts):
        return None
    return ":".join(p.zfill(2) for p in parts)


def is_private_mac(mac):
    """MAC aleatório ("endereço privado" de iPhone/Android/Windows): bit 'localmente administrado'."""
    try:
        return bool(int(mac.split(":")[0], 16) & 2)
    except (ValueError, AttributeError, IndexError):
        return False


def parse_expire(text):
    """'1m33s', '38s', '2h1m', 'permanent', 'expired' → segundos (None = sem prazo)."""
    text = (text or "").strip().lower()
    if not text or text in ("permanent", "(none)"):
        return None
    if text == "expired":
        return 0
    total, found = 0, False
    for n, unit in re.findall(r"(\d+)([hms])", text):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
        found = True
    return total if found else None


def parse_arp_macos(text):
    """Saída de 'arp -anl' → [{'ip', 'mac', 'expire', 'iface'}] (sem incompletos, multicast e broadcast)."""
    out = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 2 or cols[0] == "Neighbor":
            continue
        try:
            ip = ipaddress.ip_address(cols[0])
        except ValueError:
            continue
        mac = norm_mac(cols[1])
        if not mac or ip.version != 4 or ip.is_multicast or ip.is_link_local or mac in ("ff:ff:ff:ff:ff:ff",):
            continue
        if mac.startswith("01:00:5e"):
            continue
        expire = parse_expire(cols[2]) if len(cols) > 2 else None
        iface = next((c for c in cols[3:] if re.match(r"^(en|eth|wl|bridge)\w*$", c)), None)
        out.append({"ip": str(ip), "mac": mac, "expire": expire, "iface": iface})
    return out


def parse_ip_neigh(text):
    """Linux: saída de 'ip -4 neigh' → mesmo formato de parse_arp_macos (expire = 0 quando STALE)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)\s+lladdr\s+(\S+).*?\s(\w+)\s*$", line.strip())
        if not m:
            continue
        mac = norm_mac(m.group(3))
        if not mac:
            continue
        fresh = m.group(4) in ("REACHABLE", "DELAY", "PROBE", "PERMANENT")
        out.append({"ip": m.group(1), "mac": mac, "expire": None if fresh else 0, "iface": m.group(2)})
    return out


def alive_arp(entries):
    """IPs com entrada ARP válida. Aparelho que bloqueia ping (Windows, alguns Android) ainda responde
    ARP; quem saiu da rede some da tabela quando o prazo acaba (poucos minutos no macOS)."""
    return {e["ip"] for e in entries if e["expire"] is None or e["expire"] > 0}


def parse_ifconfig_inet(text, ip):
    """Máscara da interface que tem o IP (macOS: 'netmask 0xffffff00'; Linux: '/24' no 'ip addr')."""
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^inet (\S+) netmask (0x[0-9a-f]+)", line)
        if m and m.group(1) == ip:
            return bin(int(m.group(2), 16)).count("1")
        m = re.match(r"^inet (\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m and m.group(1) == ip:
            return int(m.group(2))
    return None


def parse_ifconfig_ether(text):
    m = re.search(r"\bether ([0-9a-f:]{11,17})", text)
    return norm_mac(m.group(1)) if m else None


def own_macs():
    """Todos os MACs desta máquina (cabo e Wi-Fi): ela aparece na rede, mas não é "uso" de ninguém."""
    if IS_MAC:
        out = run_cmd(["ifconfig"])[1]
        return {m for m in (norm_mac(x) for x in re.findall(r"\bether ([0-9a-f:]{11,17})", out)) if m}
    macs = set()
    try:
        for iface in os.listdir("/sys/class/net"):
            with open("/sys/class/net/%s/address" % iface) as f:
                mac = norm_mac(f.read())
            if mac and mac != "00:00:00:00:00:00":
                macs.add(mac)
    except OSError:
        pass
    return macs


def own_interface():
    """(ip, prefixo, mac) desta máquina na rede de casa."""
    ip = local_ip()
    if not ip:
        return None, None, None
    if IS_MAC:
        code, out = run_cmd(["ifconfig"])
        prefix = parse_ifconfig_inet(out, ip)
        mac = None
        for block in re.split(r"\n(?=\S)", out):
            if "inet %s " % ip in block:
                mac = parse_ifconfig_ether(block)
        return ip, prefix, mac
    code, out = run_cmd(["ip", "-4", "addr"])
    prefix = parse_ifconfig_inet(out, ip)
    mac = None
    for block in re.split(r"\n(?=\d+:)", out):
        m = re.match(r"^\d+: ([^:@\s]+)", block)
        if m and "inet %s/" % ip in block:
            try:
                with open("/sys/class/net/%s/address" % m.group(1)) as f:
                    mac = norm_mac(f.read())
            except OSError:
                pass
    return ip, prefix, mac


def scan_targets(ip, prefix):
    """IPs da rede para pingar (no máximo /22, para não varrer redes enormes)."""
    net = ipaddress.ip_network("%s/%d" % (ip, max(22, min(prefix or 24, 30))), strict=False)
    return [str(h) for h in net.hosts() if str(h) != ip]


def ping_once(host):
    args = ["/sbin/ping", "-c", "1", "-t", "1", host] if IS_MAC else ["ping", "-c", "1", "-W", "1", host]
    return run_cmd(args, timeout=3)[0] == 0


def read_arp():
    if IS_MAC:
        return parse_arp_macos(run_cmd(["arp", "-anl"])[1])
    return parse_ip_neigh(run_cmd(["ip", "-4", "neigh"])[1])


def sweep(ip, prefix, workers=64):
    """Pinga a rede toda em paralelo. Retorna (quem respondeu ao ping, tabela ARP depois da varredura)."""
    targets = scan_targets(ip, prefix)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        replies = {h for h, ok in zip(targets, pool.map(ping_once, targets)) if ok}
    return replies, read_arp()


# --- nomes: mDNS (Apple, impressoras, Linux), NetBIOS (Windows, TVs) ---

def dns_name(labels):
    out = b""
    for label in labels:
        raw = label.encode("idna") if label else b""
        out += struct.pack("B", len(raw)) + raw
    return out + b"\x00"


def mdns_ptr_query(ip, qid=0):
    """Consulta PTR reversa (x.x.x.x.in-addr.arpa) no formato DNS."""
    labels = list(reversed(ip.split("."))) + ["in-addr", "arpa"]
    return struct.pack(">HHHHHH", qid, 0, 1, 0, 0, 0) + dns_name(labels) + struct.pack(">HH", 12, 1)


def read_name(data, pos, depth=0):
    """Lê um nome DNS (com compressão) a partir de pos. Retorna (nome, próxima posição)."""
    labels, jumped, end = [], False, pos
    while depth < 20:
        if pos >= len(data):
            raise ValueError("truncated")
        n = data[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(data):
                raise ValueError("truncated")
            ptr = ((n & 0x3F) << 8) | data[pos + 1]
            if not jumped:
                end = pos + 2
            pos, jumped, depth = ptr, True, depth + 1
            continue
        labels.append(data[pos + 1:pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    return ".".join(labels), (end if jumped else pos)


def parse_ptr_answer(data):
    """Primeiro PTR da resposta DNS → nome sem '.local' (ou None)."""
    try:
        qd, an = struct.unpack(">HH", data[4:8])
        pos = 12
        for _ in range(qd):
            _, pos = read_name(data, pos)
            pos += 4
        for _ in range(an):
            _, pos = read_name(data, pos)
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
            pos += 10
            if rtype == 12:
                name, _ = read_name(data, pos)
                return clean_hostname(name)
            pos += rdlen
    except (ValueError, struct.error, IndexError):
        return None
    return None


def clean_hostname(name):
    name = (name or "").strip().rstrip(".")
    for suffix in (".local", ".lan", ".home", ".localdomain"):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:63]
    return name or None


def mdns_lookup(ip, timeout=1.0):
    """Pergunta o nome ao grupo mDNS a partir de porta comum: quem responde manda direto para nós
    (consulta "legada", RFC 6762 §6.7)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.sendto(mdns_ptr_query(ip, qid=0x5748), ("224.0.0.251", 5353))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                break
            name = parse_ptr_answer(data)
            if name:
                return name
    except OSError:
        return None
    finally:
        s.close()
    return None


def netbios_query():
    # consulta de status do nó (NBSTAT) para o nome curinga "*"
    name = b"\x20" + b"".join(bytes([0x41 + (c >> 4), 0x41 + (c & 0xF)]) for c in b"*" + b"\x00" * 15) + b"\x00"
    return struct.pack(">HHHHHH", 0x5749, 0, 1, 0, 0, 0) + name + struct.pack(">HH", 0x21, 1)


def parse_netbios_answer(data):
    """Resposta NBSTAT → nome da máquina (primeiro nome único com sufixo 0x00)."""
    try:
        pos = 12
        _, pos = read_name(data, pos)
        pos += 10                        # tipo, classe, TTL, tamanho
        count = data[pos]
        pos += 1
        for i in range(count):
            raw = data[pos + i * 18:pos + i * 18 + 18]
            if len(raw) < 18:
                break
            name, suffix, flags = raw[:15], raw[15], struct.unpack(">H", raw[16:18])[0]
            if suffix == 0 and not flags & 0x8000:
                return clean_hostname(name.decode("ascii", "replace").strip())
    except (ValueError, struct.error, IndexError):
        return None
    return None


def netbios_lookup(ip, timeout=0.8):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(netbios_query(), (ip, 137))
        data, _ = s.recvfrom(1024)
        return parse_netbios_answer(data)
    except OSError:
        return None
    finally:
        s.close()


KIND_PATTERNS = [
    ("phone", r"iphone|android|galaxy|\bsm-[a-z]|redmi|xiaomi|poco|motorola|\bmoto|pixel|oneplus|huawei|realme"),
    ("tablet", r"ipad|tablet|\btab\b|kindle"),
    ("watch", r"watch"),
    ("tv", r"\btv\b|tv-|-tv|webos|bravia|roku|chromecast|fire-?tv|appletv|apple-tv|smarttv|tizen|androidtv"),
    ("console", r"playstation|\bps[345]\b|xbox|nintendo|switch"),
    ("printer", r"printer|\bhp[0-9a-f]{6}|epson|brother|canon|laserjet|deskjet|officejet"),
    ("speaker", r"echo|alexa|google-?home|nest|homepod|sonos"),
    ("computer", r"macbook|imac|mac-?mini|mac-?pro|\bmac\b|laptop|desktop|notebook|\bpc\b|windows|thinkpad|ubuntu"),
    ("router", r"router|gateway|tp-?link|archer|deco|mesh|repeater|extender"),
    ("camera", r"\bcam|camera|ipcam|intelbras|hikvision|yi-|wyze"),
]


def guess_kind(name):
    n = (name or "").lower()
    for kind, pattern in KIND_PATTERNS:
        if re.search(pattern, n):
            return kind
    return None


# --------------------------------------------------------------------------
# domínios: categoria e domínio principal

# sufixos de dois níveis mais comuns (sem baixar a Public Suffix List: o painel funciona offline)
MULTI_SUFFIXES = {
    "com.br", "net.br", "org.br", "gov.br", "edu.br", "art.br", "blog.br", "app.br", "tv.br", "jus.br", "leg.br", "mil.br",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "co.jp", "ne.jp", "com.cn", "net.cn", "org.cn",
    "com.ar", "com.mx", "co.za", "com.tr", "com.sg", "com.hk", "co.kr", "co.in", "co.nz", "com.pt",
}
# Domínios conhecidos → categoria. A chave casa com o domínio e com qualquer subdomínio dele.
CATEGORIES = {
    "social": ["facebook.com", "fbcdn.net", "facebook.net", "instagram.com", "cdninstagram.com", "tiktok.com",
               "tiktokcdn.com", "tiktokv.com", "tiktokcdn-us.com", "byteoversea.com", "ibytedtos.com", "musical.ly",
               "twitter.com", "x.com", "twimg.com", "t.co", "snapchat.com", "sc-cdn.net", "snapkit.com", "pinterest.com",
               "pinimg.com", "reddit.com", "redd.it", "redditmedia.com", "redditstatic.com", "linkedin.com", "licdn.com",
               "threads.net", "threads.com", "kwai.com", "kwai.net", "kuaishou.com", "tumblr.com", "bsky.app", "vk.com"],
    "video": ["youtube.com", "googlevideo.com", "ytimg.com", "youtu.be", "youtube-nocookie.com", "netflix.com",
              "nflxvideo.net", "nflxso.net", "nflximg.net", "nflxext.com", "primevideo.com", "aiv-cdn.net",
              "disneyplus.com", "disney-plus.net", "bamgrid.com", "dssott.com", "max.com", "hbomax.com", "hbo.com",
              "globoplay.globo.com", "globo.com", "glbimg.com", "twitch.tv", "ttvnw.net", "jtvnw.net", "vimeo.com",
              "vimeocdn.com", "crunchyroll.com", "paramountplus.com", "pluto.tv", "tv.apple.com", "dazn.com",
              "starplus.com", "kick.com"],
    "music": ["spotify.com", "scdn.co", "spotifycdn.com", "deezer.com", "dzcdn.net", "music.apple.com",
              "soundcloud.com", "sndcdn.com", "tidal.com", "music.youtube.com", "audible.com", "pandora.com"],
    "games": ["roblox.com", "rbxcdn.com", "roblox.cn", "epicgames.com", "epicgames.dev", "unrealengine.com",
              "fortnite.com", "steampowered.com", "steamcommunity.com", "steamcontent.com", "steamstatic.com",
              "playstation.net", "playstation.com", "sonyentertainmentnetwork.com", "xboxlive.com", "xbox.com",
              "minecraft.net", "mojang.com", "riotgames.com", "leagueoflegends.com", "ea.com", "origin.com",
              "nintendo.net", "nintendo.com", "supercell.com", "garena.com", "freefiremobile.com", "battle.net",
              "blizzard.com", "activision.com", "callofduty.com", "ubisoft.com", "miniclip.com", "chess.com",
              "gamepass.com", "brawlstars.com", "clashroyale.com"],
    "messaging": ["whatsapp.com", "whatsapp.net", "telegram.org", "t.me", "discord.com", "discord.gg",
                  "discordapp.com", "discordapp.net", "signal.org", "messenger.com", "skype.com", "viber.com",
                  "gmail.com", "mail.google.com", "mail.yahoo.com", "icloud-mail.apple.com"],
    "shopping": ["amazon.com", "amazon.com.br", "media-amazon.com", "ssl-images-amazon.com", "mercadolivre.com.br",
                 "mercadolibre.com", "mlstatic.com", "mercadopago.com", "shopee.com.br", "shopee.com", "susercontent.com",
                 "magazineluiza.com.br", "magalu.com", "aliexpress.com", "alicdn.com", "shein.com", "ltwebstatic.com",
                 "americanas.com.br", "casasbahia.com.br", "temu.com", "ifood.com.br", "rappi.com", "ebay.com"],
    "news": ["uol.com.br", "g1.globo.com", "folha.uol.com.br", "estadao.com.br", "cnnbrasil.com.br", "bbc.com",
             "bbc.co.uk", "cnn.com", "nytimes.com", "terra.com.br", "r7.com", "metropoles.com", "infomoney.com.br",
             "theguardian.com", "reuters.com", "apnews.com"],
    "work": ["office.com", "office365.com", "microsoftonline.com", "sharepoint.com", "teams.microsoft.com",
             "outlook.com", "zoom.us", "zoom.com", "slack.com", "slack-edge.com", "notion.so", "notion.com",
             "github.com", "githubusercontent.com", "atlassian.net", "atlassian.com", "jira.com", "figma.com",
             "docs.google.com", "drive.google.com", "meet.google.com", "classroom.google.com", "dropbox.com",
             "canva.com", "trello.com", "asana.com", "chatgpt.com", "openai.com", "claude.ai", "anthropic.com",
             "gemini.google.com", "stackoverflow.com", "webex.com", "cloud.microsoft", "office.net",
             "microsoft365.com", "onedrive.com", "sharepointonline.com", "slackb.com", "claude.com", "warp.dev",
             "service-now.com", "servicenow.com", "duolingo.com", "linear.app", "miro.com", "loom.com",
             "vercel.com", "gitlab.com", "bitbucket.org"],
    "search": ["google.com", "google.com.br", "bing.com", "duckduckgo.com", "yahoo.com", "wikipedia.org",
               "wikimedia.org", "ecosia.org"],
    "ads": ["doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com",
            "googletagmanager.com", "googletagservices.com", "adnxs.com", "criteo.com", "criteo.net", "taboola.com",
            "outbrain.com", "scorecardresearch.com", "hotjar.com", "app-measurement.com", "appsflyer.com",
            "adjust.com", "branch.io", "amplitude.com", "mixpanel.com", "segment.io", "crashlytics.com",
            "unityads.unity3d.com", "applovin.com", "moatads.com", "rubiconproject.com", "pubmatic.com",
            "casalemedia.com", "adsrvr.org", "facebook.net",
            # SDKs de anúncio de apps e jogos de celular (vistos numa casa de verdade)
            "moloco.com", "amazon-adsystem.com", "pangle.io", "pangle-b.io", "inner-active.mobi", "inmobi.com",
            "unity3d.com", "mtgglobals.com", "mintegral.com", "rayjump.com", "bidmachine.io", "vungle.com",
            "liftoff.io", "chartboost.com", "supersonicads.com", "ironsrc.mobi", "adjust.io", "adcolony.com",
            "tapjoy.com", "fyber.com", "smaato.net", "everestop.io", "blueduckredapple.com", "thecatmachine.com",
            "app-ads-services.com", "app-analytics-services.com", "applovin.net", "applvn.com"],
    "system": ["apple.com", "icloud.com", "icloud-content.com", "mzstatic.com", "apple-dns.net", "aaplimg.com",
               "cdn-apple.com", "push.apple.com", "itunes.apple.com", "apple.news", "googleapis.com", "gstatic.com",
               "gvt1.com", "gvt2.com", "1e100.net", "android.com", "googleusercontent.com", "clients.google.com",
               "connectivitycheck.gstatic.com", "play.googleapis.com", "microsoft.com", "windowsupdate.com",
               "msftconnecttest.com", "msftncsi.com", "live.com", "msn.com", "bing.net", "akamai.net",
               "akamaiedge.net", "akamaihd.net", "akadns.net", "edgekey.net", "edgesuite.net", "cloudfront.net",
               "amazonaws.com", "cloudflare.com", "cloudflare-dns.com", "fastly.net", "fastly-edge.com", "ntp.org",
               "pool.ntp.org", "time.apple.com", "time.windows.com", "samsung.com", "samsungcloud.com",
               "samsungqbe.com", "lgtvsdp.com", "lge.com", "xiaomi.com", "miui.com", "mi.com", "tplinkcloud.com",
               "tp-link.com", "amazon-dns.com", "a2z.com", "amazonvideo.com", "digicert.com", "sectigo.com",
               "letsencrypt.org", "ocsp.digicert.com", "adguard.com", "adtidy.org", "mozilla.org", "mozilla.net",
               "firefox.com", "spotify.map.fastly.net", "nflxext.com.edgesuite.net", "doh.dns.apple.com",
               "trendmicro.com", "mcafee.com", "avast.com", "kaspersky.com", "trafficmanager.net", "root-servers.net",
               "lencr.org", "sentry.io", "safebrowsing.apple", "gvt3.com", "yahoodns.net", "msidentity.com",
               "static.microsoft", "azure.com", "azure-devices.net", "azureedge.net", "windows.com", "windows.net",
               "vercel-dns.com", "adblockplus.org", "apple-cloudkit.com", "ntp.br", "office.com.edgekey.net"],
}
# Apps: nomes próprios (não são traduzidos). A chave casa com o domínio e com os subdomínios dele.
APPS = {
    "WhatsApp": ["whatsapp.com", "whatsapp.net"], "Instagram": ["instagram.com", "cdninstagram.com"],
    "Facebook": ["facebook.com", "fbcdn.net", "messenger.com"], "TikTok": ["tiktok.com", "tiktokcdn.com", "tiktokv.com",
    "tiktokcdn-us.com", "byteoversea.com", "ibytedtos.com"], "YouTube": ["youtube.com", "googlevideo.com", "ytimg.com",
    "youtu.be"], "YouTube Music": ["music.youtube.com"], "Netflix": ["netflix.com", "nflxvideo.net", "nflxso.net",
    "nflximg.net", "nflxext.com"], "Prime Video": ["primevideo.com", "aiv-cdn.net"], "Disney+": ["disneyplus.com",
    "disney-plus.net", "bamgrid.com", "dssott.com"], "Max": ["max.com", "hbomax.com"], "Globoplay": ["globoplay.globo.com"],
    "Twitch": ["twitch.tv", "ttvnw.net", "jtvnw.net"], "Spotify": ["spotify.com", "scdn.co", "spotifycdn.com"],
    "Deezer": ["deezer.com", "dzcdn.net"], "X": ["twitter.com", "x.com", "twimg.com"], "LinkedIn": ["linkedin.com",
    "licdn.com"], "Pinterest": ["pinterest.com", "pinimg.com"], "Reddit": ["reddit.com", "redd.it", "redditmedia.com",
    "redditstatic.com"], "Kwai": ["kwai.com", "kwai.net"], "Telegram": ["telegram.org", "t.me"], "Discord": ["discord.com",
    "discord.gg", "discordapp.com", "discordapp.net"], "Gmail": ["gmail.com", "mail.google.com"],
    "Microsoft 365": ["office.com", "office365.com", "microsoftonline.com", "sharepoint.com", "sharepointonline.com",
                      "outlook.com", "cloud.microsoft", "office.net", "microsoft365.com", "onedrive.com"],
    "Teams": ["teams.microsoft.com", "teams.live.com"], "Zoom": ["zoom.us", "zoom.com"], "Slack": ["slack.com",
    "slack-edge.com", "slackb.com"], "GitHub": ["github.com", "githubusercontent.com"], "Notion": ["notion.so", "notion.com"],
    "Google Docs": ["docs.google.com", "drive.google.com"], "Google Meet": ["meet.google.com"], "ChatGPT": ["chatgpt.com",
    "openai.com"], "Claude": ["claude.ai", "claude.com", "anthropic.com"], "Gemini": ["gemini.google.com"],
    "Duolingo": ["duolingo.com"], "Google": ["google.com", "google.com.br"], "Bing": ["bing.com"],
    "Wikipedia": ["wikipedia.org", "wikimedia.org"], "Amazon": ["amazon.com", "amazon.com.br", "media-amazon.com",
    "ssl-images-amazon.com"], "Mercado Livre": ["mercadolivre.com.br", "mercadolibre.com", "mlstatic.com",
    "mercadopago.com"], "Shopee": ["shopee.com.br", "shopee.com", "susercontent.com"], "Shein": ["shein.com",
    "ltwebstatic.com"], "AliExpress": ["aliexpress.com", "alicdn.com"], "iFood": ["ifood.com.br"],
    "Roblox": ["roblox.com", "rbxcdn.com"], "Fortnite": ["fortnite.com", "epicgames.com", "epicgames.dev"],
    "Minecraft": ["minecraft.net", "mojang.com"], "PlayStation": ["playstation.net", "playstation.com"],
    "Xbox": ["xboxlive.com", "xbox.com"], "Steam": ["steampowered.com", "steamcommunity.com", "steamcontent.com",
    "steamstatic.com"], "Free Fire": ["freefiremobile.com", "garena.com"], "Uol": ["uol.com.br"], "g1": ["g1.globo.com"],
}
APP_OF = {}
for _app, _domains in APPS.items():
    for _d in _domains:
        APP_OF[_d] = _app
CATEGORY_OF = {}
for _cat, _domains in CATEGORIES.items():
    for _d in _domains:
        CATEGORY_OF.setdefault(_d, _cat)
# Categorias que não contam como "uso" (o aparelho faz isso sozinho, mesmo parado). "other" também fica de fora:
# numa casa real, a maior parte dos sites sem categoria é tráfego automático (antivírus, telemetria, anúncios).
PASSIVE_CATEGORIES = ("system", "ads", "other")
BLOCK_REASONS = ("FilteredBlackList", "FilteredBlockedService", "FilteredSafeBrowsing", "FilteredParental",
                 "FilteredInvalid")


def base_domain(name):
    """'www.g1.globo.com' → 'globo.com'; 'a.b.com.br' → 'b.com.br'."""
    parts = [p for p in (name or "").lower().rstrip(".").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in MULTI_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def lookup_suffix(table, name):
    """Valor do domínio mais específico que estiver na tabela (g1.globo.com antes de globo.com)."""
    parts = (name or "").lower().rstrip(".").split(".")
    for i in range(len(parts)):
        hit = table.get(".".join(parts[i:]))
        if hit:
            return hit
    return None


def categorize(name):
    return lookup_suffix(CATEGORY_OF, name) or "other"


def app_of(name):
    return lookup_suffix(APP_OF, name)


def display_domain(name):
    """Domínio que aparece no painel: o principal, exceto quando um subdomínio tem categoria própria
    (music.youtube.com, g1.globo.com)."""
    parts = (name or "").lower().rstrip(".").split(".")
    base = base_domain(name)
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in CATEGORY_OF and len(cand) > len(base):
            return cand
        if cand == base:
            break
    return base


def is_local_name(name):
    n = (name or "").lower().rstrip(".")
    # ".box" é o domínio interno dos roteadores da Claro/NET; "wpad.*" é a busca automática de proxy do Windows
    return (not n or "." not in n or n.endswith((".local", ".arpa", ".lan", ".home", ".localdomain", ".internal",
                                                 ".box", ".invalid", ".localhost"))
            or n in ("localhost", "wpad") or n.startswith("wpad."))


# --------------------------------------------------------------------------
# AdGuard Home: registro de consultas e clientes

TIME_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$")


def parse_rfc3339(text):
    """'2026-11-02T21:29:14.123456789-03:00' → epoch. (fromisoformat do 3.8 não lê nanossegundos nem 'Z'.)"""
    m = TIME_RE.match((text or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = float("0." + m.group(7)) if m.group(7) else 0.0
    tz = m.group(8)
    if not tz:
        return datetime(y, mo, d, h, mi, s).timestamp() + frac
    if tz == "Z":
        offset = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        hh, mm = int(tz[1:3]), int(tz[-2:])
        offset = sign * timedelta(hours=hh, minutes=mm)
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone(offset)).timestamp() + frac


def parse_querylog_entry(e):
    """Entrada do /control/querylog → {'ts', 'ip', 'name', 'blocked'} (None para o que não interessa)."""
    if not isinstance(e, dict):
        return None
    q = e.get("question") or {}
    name = str(q.get("name") or "").lower().rstrip(".")
    if q.get("type") in ("PTR", "SOA", "SRV") or is_local_name(name):
        return None
    ts = parse_rfc3339(e.get("time"))
    ip = str(e.get("client") or "")
    if ts is None or not ip:
        return None
    return {"ts": ts, "ip": ip, "name": name, "blocked": e.get("reason") in BLOCK_REASONS}


class AdGuard:
    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def configured(self):
        return bool(self.cfg.get("adguard_user") and self.cfg.get("adguard_password"))

    def get(self, path, params=None, timeout=10):
        url = self.cfg["adguard_url"].rstrip("/") + path + ("?" + urlencode(params) if params else "")
        return fetch_json(url, timeout=timeout, auth=(self.cfg["adguard_user"], self.cfg["adguard_password"]))

    def querylog(self, older_than=None, limit=500):
        params = {"limit": limit}
        if older_than:
            params["older_than"] = older_than
        return self.get("/control/querylog", params)

    def client_names(self):
        """{ip ou mac: nome} dos clientes cadastrados no AdGuard (persistentes) e dos que ele descobriu."""
        data = self.get("/control/clients")
        names = {}
        for c in data.get("auto_clients") or []:
            if c.get("name") and c.get("ip"):
                names[c["ip"]] = ("adguard_auto", c["name"])
        for c in data.get("clients") or []:
            for ident in c.get("ids") or []:
                key = norm_mac(ident) or ident
                if c.get("name"):
                    names[key] = ("adguard", c["name"])
        return names


def error_text(e):
    if isinstance(e, HTTPError):
        return "HTTP %d%s" % (e.code, " (%s)" % tr("err.auth") if e.code in (401, 403) else "")
    if isinstance(e, URLError):
        return str(e.reason)
    return str(e)


# --------------------------------------------------------------------------
# avisos no celular (ntfy)

class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self.wake = threading.Event()

    @property
    def enabled(self):
        return bool(self.cfg.get("ntfy_topic"))

    def queue(self, db, title, body, tag):
        if self.enabled:
            db.execute("INSERT INTO notifications(ts, title, body, tag) VALUES(?,?,?,?)", (time.time(), title, body, tag))
            self.wake.set()

    def send(self, title, body, tags):
        payload = json.dumps({"topic": self.cfg["ntfy_topic"], "title": title, "message": body,
                              "tags": tags}).encode("utf-8")
        url = self.cfg["ntfy_server"].rstrip("/") + "/"
        # curl do sistema usa os certificados do sistema (o ssl do Python 3.8 do macOS pode não ter os atuais)
        curl = "/usr/bin/curl" if os.path.exists("/usr/bin/curl") else shutil.which("curl")
        if not curl:
            try:
                req = Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "who-is-home"})
                urlopen(req, timeout=15).read()
                return True, ""
            except Exception as e:
                return False, str(e)
        try:
            r = subprocess.run([curl, "-q", "-sS", "-f", "-m", "15", "-H", "Content-Type: application/json",
                                "--data-binary", "@-", url], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return False, str(e)
        return r.returncode == 0, r.stderr.decode("utf-8", "replace").strip()

    def run(self):
        db = connect()
        while True:
            if self.wake.wait(30):
                self.wake.clear()
            if not self.enabled:
                continue
            rows = db.execute("SELECT id, title, body, tag FROM notifications WHERE sent_ts IS NULL ORDER BY id LIMIT 10").fetchall()
            for nid, title, body, tag in rows:
                ok, err = self.send(title, body, [tag])
                if not ok:
                    log(tr("log.notify_failed", err=err))
                    break
                with WRITE:
                    db.execute("UPDATE notifications SET sent_ts=? WHERE id=?", (time.time(), nid))
                    db.commit()


# --------------------------------------------------------------------------
# coletor: presença, nomes e consultas

def device_label(row):
    """Nome para avisos: apelido > nome descoberto > IP."""
    nickname, hostname, ip = row
    return nickname or hostname or ip or "?"


class Collector:
    def __init__(self, cfg, notifier):
        self.cfg = cfg
        self.notifier = notifier
        self.adguard = AdGuard(cfg)
        self.ipmac = {}               # ip → mac (tabela ARP mais recente)
        self.own = (None, None, None)
        self.own_macs = own_macs()
        self.lock = threading.Lock()
        self.status = {"adguard": "unset", "adguard_error": None, "last_poll": None, "last_scan": None,
                       "scan_devices": 0}
        self.stop_flag = threading.Event()

    # --- presença ---

    def mark_seen(self, db, mac, ip, ts, via_dns=False):
        """Aparelho deu sinal: cria se for novo (com aviso), abre sessão se estava desligado."""
        row = db.execute("SELECT online, last_seen, nickname, hostname FROM devices WHERE mac=?", (mac,)).fetchone()
        if row is None:
            # placas desta máquina já entram fora das somas (o tráfego dela é do down-again e do próprio coletor)
            db.execute("INSERT INTO devices(mac, ip, first_seen, last_seen, last_dns, online, hidden) VALUES(?,?,?,?,?,1,?)",
                       (mac, ip, ts, ts, ts if via_dns else None, 1 if mac in self.own_macs else 0))
            db.execute("INSERT INTO presence(mac, start_ts, end_ts) VALUES(?,?,NULL)", (mac, ts))
            db.execute("INSERT INTO events(ts, kind, mac, detail) VALUES(?,?,?,?)", (ts, "new", mac, ip))
            if state_get(db, "bootstrapped") == "1" and self.cfg.get("notify_new_devices"):
                name = ip
                self.notifier.queue(db, tr("notify.new.title"),
                                    tr("notify.new.body", name=name, ip=ip, time=time.strftime("%H:%M", time.localtime(ts))),
                                    "bell")
            log(tr("log.new_device", name=ip, ip=ip, mac=mac))
            return
        online, last_seen = row[0], row[1] or 0
        db.execute("UPDATE devices SET ip=?, last_seen=MAX(COALESCE(last_seen, 0), ?), online=1%s WHERE mac=?" %
                   (", last_dns=MAX(COALESCE(last_dns, 0), ?)" if via_dns else ""),
                   (ip, ts, ts, mac) if via_dns else (ip, ts, mac))
        db.execute("UPDATE devices SET first_seen=? WHERE mac=? AND first_seen IS NULL", (ts, mac))   # vindo do known_devices
        if not online:
            db.execute("INSERT INTO presence(mac, start_ts, end_ts) VALUES(?,?,NULL)", (mac, max(ts, last_seen)))

    def close_stale(self, db, now):
        """Quem ficou sem sinal por offline_minutes vira desligado; a sessão termina no último sinal."""
        limit = now - self.cfg["offline_minutes"] * 60
        for mac, last_seen in db.execute("SELECT mac, last_seen FROM devices WHERE online=1 AND last_seen < ?",
                                         (limit,)).fetchall():
            db.execute("UPDATE devices SET online=0 WHERE mac=?", (mac,))
            db.execute("UPDATE presence SET end_ts=? WHERE mac=? AND end_ts IS NULL", (last_seen, mac))

    def recover(self, db):
        """Ao iniciar: sessões abertas de quando o programa parou terminam no último sinal."""
        db.execute("UPDATE presence SET end_ts=(SELECT last_seen FROM devices d WHERE d.mac=presence.mac) "
                   "WHERE end_ts IS NULL")
        db.execute("UPDATE devices SET online=0")
        apply_known_devices(db, self.cfg.get("known_devices") or {})

    # --- varredura ---

    def scan(self, db):
        ip, prefix, mac = own_interface()
        self.own = (ip, prefix, mac)
        if not ip:
            return
        replies, arp = sweep(ip, prefix)
        fresh = alive_arp(arp)
        now = time.time()
        with self.lock:
            self.ipmac = {e["ip"]: e["mac"] for e in arp}
            if mac:
                self.ipmac[ip] = mac
        seen = [(e["mac"], e["ip"]) for e in arp if e["ip"] in replies or e["ip"] in fresh]
        if mac:
            seen.append((mac, ip))
        with WRITE:
            for m, i in seen:
                self.mark_seen(db, m, i, now)
            self.close_stale(db, now)
            if state_get(db, "bootstrapped") != "1":
                state_set(db, "bootstrapped", "1")     # a primeira varredura não gera aviso de "aparelho novo"
            db.commit()
        self.status["last_scan"] = now
        self.status["scan_devices"] = len(seen)

    def mac_for(self, ip):
        own_ip, _, own_mac = self.own
        if ip in ("127.0.0.1", "::1") or ip == own_ip:
            return own_mac
        with self.lock:
            mac = self.ipmac.get(ip)
        if mac is None:
            arp = read_arp()
            with self.lock:
                self.ipmac.update({e["ip"]: e["mac"] for e in arp})
                mac = self.ipmac.get(ip)
        return mac

    # --- consultas do AdGuard ---

    def fetch_new(self, cursor, max_pages):
        """Busca no AdGuard as consultas mais novas que o cursor (o registro vem do mais novo ao mais velho)."""
        out, older, pages = [], None, 0
        while pages < max_pages:
            data = self.adguard.querylog(older_than=older)
            pages += 1
            items = data.get("data") or []
            done = not items
            for e in items:
                parsed = parse_querylog_entry(e)
                ts = parse_rfc3339(e.get("time")) if isinstance(e, dict) else None
                if ts is not None and ts <= cursor:
                    done = True
                    break
                if parsed:
                    out.append(parsed)
            older = data.get("oldest")
            if done or not older:
                break
        out.sort(key=lambda x: x["ts"])
        return out

    def poll(self, db):
        if not self.adguard.configured:
            self.status["adguard"] = "unset"
            return
        cursor = float(state_get(db, "ql_cursor") or 0)
        first = cursor == 0
        if first:
            cursor = time.time() - 86400          # primeira execução: importa as últimas 24h
        try:
            entries = self.fetch_new(cursor, 400 if first else 40)
        except Exception as e:
            self.status["adguard"] = "error"
            self.status["adguard_error"] = error_text(e)
            return
        self.status["adguard"] = "ok"
        self.status["adguard_error"] = None
        self.status["last_poll"] = time.time()
        if not entries and not first:
            return
        resolved = []
        for e in entries:
            mac = self.mac_for(e["ip"])
            if mac:
                resolved.append(dict(e, mac=mac))
        with WRITE:
            ingest(db, resolved, self.cfg["activity_min_queries"], self)
            state_set(db, "ql_cursor", max([cursor] + [e["ts"] for e in entries]))
            db.commit()

    # --- nomes ---

    def find_names(self, db):
        limit = time.time() - self.cfg["names_minutes"] * 60
        rows = db.execute("SELECT mac, ip, hostname, name_source FROM devices WHERE online=1 AND "
                          "(names_ts IS NULL OR names_ts < ?)", (limit,)).fetchall()
        if not rows:
            return
        ad_names = {}
        if self.adguard.configured:
            try:
                ad_names = self.adguard.client_names()
            except Exception:
                ad_names = {}
        for mac, ip, hostname, source in rows:
            found = None
            if mac in ad_names and ad_names[mac][0] == "adguard":
                found = ad_names[mac]
            elif ip in ad_names and ad_names[ip][0] == "adguard":
                found = ad_names[ip]
            else:
                name = mdns_lookup(ip)
                if name:
                    found = ("mdns", name)
                else:
                    name = netbios_lookup(ip)
                    if name:
                        found = ("netbios", name)
                    elif ip in ad_names:
                        found = ad_names[ip]
            with WRITE:
                if found:
                    db.execute("UPDATE devices SET hostname=?, name_source=?, names_ts=?, "
                               "kind=COALESCE(kind, ?) WHERE mac=?",
                               (found[1], found[0], time.time(), guess_kind(found[1]), mac))
                else:
                    db.execute("UPDATE devices SET names_ts=? WHERE mac=?", (time.time(), mac))
                db.commit()

    # --- manutenção e resumo semanal ---

    def housekeeping(self, db):
        now = time.time()
        if float(state_get(db, "pruned", 0)) > now - 86400:
            return
        keep = now - self.cfg["keep_days"] * 86400
        with WRITE:
            db.execute("DELETE FROM activity WHERE minute < ?", (int(keep // 60),))
            db.execute("DELETE FROM domains WHERE day < ?", (day_str(keep),))
            db.execute("DELETE FROM hourly WHERE day < ?", (day_str(keep),))
            db.execute("DELETE FROM presence WHERE end_ts IS NOT NULL AND end_ts < ?", (keep,))
            db.execute("DELETE FROM events WHERE ts < ?", (keep,))
            db.execute("DELETE FROM notifications WHERE sent_ts IS NOT NULL AND sent_ts < ?", (now - 30 * 86400,))
            state_set(db, "pruned", now)
            db.commit()

    def weekly(self, db):
        if not self.cfg.get("weekly_summary") or not self.notifier.enabled:
            return
        now = datetime.now()
        if now.weekday() != int(self.cfg["weekly_day"]) or now.hour != int(self.cfg["weekly_hour"]):
            return
        week = now.strftime("%Y-%W")
        if state_get(db, "weekly_sent") == week:
            return
        o = overview(db, "7d", self.cfg)
        top = ", ".join("%s (%s)" % (u["name"], fmt_minutes(u["minutes"])) for u in o["usage"][:3]) or tr("notify.none")
        new = ", ".join(n["name"] for n in o["new_devices"][:5]) or tr("notify.none")
        with WRITE:
            self.notifier.queue(db, tr("notify.weekly.title"),
                                tr("notify.weekly.body", devices=o["totals"]["active_devices"],
                                   queries=o["totals"]["queries"], blocked=o["totals"]["blocked"], top=top, new=new),
                                "bar_chart")
            state_set(db, "weekly_sent", week)
            db.commit()

    # --- laços ---

    def loop(self, name, every, step):
        db = connect()
        while not self.stop_flag.is_set():
            t0 = time.time()
            try:
                step(db)
            except sqlite3.Error as e:
                log(tr("log.db_error", err=repr(e)))
            except Exception as e:     # um erro num passo não pode derrubar o coletor
                log("%s: %r" % (name, e))
            self.stop_flag.wait(max(1.0, every() - (time.time() - t0)))

    def start(self):
        db = connect()
        with WRITE:
            self.recover(db)
            db.commit()
        db.close()
        if not self.adguard.configured:
            log(tr("log.no_adguard"))
        jobs = [("scan", lambda: self.cfg["scan_seconds"], self.scan),
                ("adguard", lambda: self.cfg["poll_seconds"], self.poll),
                ("names", lambda: 60, self.find_names),
                ("maintenance", lambda: 600, lambda db: (self.housekeeping(db), self.weekly(db)))]
        for name, every, step in jobs:
            threading.Thread(target=self.loop, args=(name, every, step), daemon=True).start()


def apply_known_devices(db, known):
    """Apelidos do config.json (known_devices): cadastra o aparelho se ainda não existe (sem aviso de
    "novo") e preenche apelido e tipo que ainda estiverem vazios. O que foi editado no painel vence."""
    for raw_mac, info in known.items():
        mac = norm_mac(raw_mac)
        if not mac or not isinstance(info, dict):
            continue
        kind = info.get("kind") if info.get("kind") in KINDS else None
        db.execute("INSERT OR IGNORE INTO devices(mac, online) VALUES(?, 0)", (mac,))   # first_seen vem no 1º sinal
        db.execute("UPDATE devices SET nickname=COALESCE(nickname, ?), kind=COALESCE(kind, ?) WHERE mac=?",
                   (str(info.get("name") or "")[:40] or None, kind, mac))


def ingest(db, entries, min_queries, collector=None):
    """Grava consultas já ligadas a um MAC: contagem por site e por hora, minutos de uso e presença.
    entries: [{'ts', 'ip', 'mac', 'name', 'blocked'}]."""
    domains, hourly, minutes, last = {}, {}, {}, {}
    for e in entries:
        ts, mac = e["ts"], e["mac"]
        day = day_str(ts)
        dom = display_domain(e["name"])
        cat = categorize(e["name"])
        blocked = 1 if e["blocked"] else 0
        k = (day, mac, dom)
        q, b, _ = domains.get(k, (0, 0, cat))
        domains[k] = (q + 1, b + blocked, cat)
        hk = (day, mac, datetime.fromtimestamp(ts).hour)
        q, b = hourly.get(hk, (0, 0))
        hourly[hk] = (q + 1, b + blocked)
        if not blocked and cat not in PASSIVE_CATEGORIES:
            mk = (mac, int(ts // 60))
            n, first_cat, first_app = minutes.get(mk, (0, cat, None))
            # categoria do minuto: a primeira consulta; app: o primeiro reconhecido
            minutes[mk] = (n + 1, first_cat, first_app or app_of(e["name"]))
        last[mac] = (e["ip"], max(ts, last.get(mac, (None, 0))[1]))
    for (day, mac, dom), (q, b, cat) in domains.items():
        db.execute("INSERT OR IGNORE INTO domains(day, mac, domain, cat, queries, blocked) VALUES(?,?,?,?,0,0)",
                   (day, mac, dom, cat))
        db.execute("UPDATE domains SET queries=queries+?, blocked=blocked+? WHERE day=? AND mac=? AND domain=?",
                   (q, b, day, mac, dom))
    for (day, mac, hour), (q, b) in hourly.items():
        db.execute("INSERT OR IGNORE INTO hourly(day, mac, hour, queries, blocked) VALUES(?,?,?,0,0)", (day, mac, hour))
        db.execute("UPDATE hourly SET queries=queries+?, blocked=blocked+? WHERE day=? AND mac=? AND hour=?",
                   (q, b, day, mac, hour))
    for (mac, minute), (n, cat, app) in minutes.items():
        if n >= min_queries:
            db.execute("INSERT OR IGNORE INTO activity(mac, minute, cat, app) VALUES(?,?,?,?)", (mac, minute, cat, app))
    if collector is not None:
        for mac, (ip, ts) in last.items():
            if ts > time.time() - collector.cfg["offline_minutes"] * 60:
                collector.mark_seen(db, mac, ip, ts, via_dns=True)
    return len(entries)


# --------------------------------------------------------------------------
# estatísticas para o painel
#
# Um aparelho pode ter vários MACs (cabo e Wi-Fi, ou o MAC privado que o celular trocou): os "filhos" apontam para o
# principal em devices.parent e tudo soma no principal, sem contar duas vezes o mesmo minuto. Aparelhos marcados
# como infraestrutura (hidden: roteador, switch, este computador) aparecem na lista, mas ficam fora das contas.

PERIODS = {"today": 1, "7d": 7, "30d": 30}
DAY_START = 5 * 60          # o dia de uso vai das 5h às 5h: quem usa à 1h da manhã ainda está "no dia anterior"
STREAK_GAP = 3              # minutos sem uso que ainda contam como a mesma sequência


def period_range(key, now=None):
    now = now or time.time()
    days = PERIODS.get(key, 1)
    t0 = (datetime.fromtimestamp(midnight(now)) - timedelta(days=days - 1)).timestamp()
    t1 = (datetime.fromtimestamp(midnight(now)) + timedelta(days=1)).timestamp()
    day_list = [day_str(t0 + 86400 * i + 3600) for i in range(days)]     # +1h: atravessa horário de verão
    return t0, min(t1, now), day_list


def month_range(month, now=None):
    """'2026-11' → (início, fim ou agora, dias). Mês inválido = mês atual."""
    now = now or time.time()
    try:
        start = datetime.strptime(month or "", "%Y-%m")
    except ValueError:
        start = datetime.fromtimestamp(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    t0, t1 = start.timestamp(), min(end.timestamp(), now)
    days, d = [], start
    while d.timestamp() < t1:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return t0, t1, days or [start.strftime("%Y-%m-%d")]


def device_rows(db):
    cols = "mac, ip, hostname, name_source, nickname, kind, first_seen, last_seen, online, person_id, parent, hidden"
    return {r[0]: {"mac": r[0], "ip": r[1], "hostname": r[2], "name_source": r[3], "nickname": r[4], "kind": r[5],
                   "first_seen": r[6], "last_seen": r[7], "online": bool(r[8]), "person_id": r[9], "parent": r[10],
                   "hidden": bool(r[11])}
            for r in db.execute("SELECT %s FROM devices" % cols).fetchall()}


def name_of(d):
    return d["nickname"] or d["hostname"] or d["ip"] or d["mac"]


def marks(values):
    return ",".join("?" * len(values))


def canon_map(devs):
    """mac → mac do aparelho principal (um nível só: pai inexistente, ele mesmo ou que também é filho é ignorado)."""
    out = {}
    for mac, d in devs.items():
        p = d["parent"]
        out[mac] = p if p and p != mac and p in devs and not devs[p]["parent"] else mac
    return out


def merge_intervals(items):
    out = []
    for a, b in sorted(items):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def merge_minutes(minutes):
    """[minuto, ...] ordenados → [[início, fim], ...] em epoch (minutos seguidos viram um trecho)."""
    out = []
    for m in minutes:
        if out and m <= out[-1][1] // 60:
            out[-1][1] = (m + 1) * 60
        else:
            out.append([m * 60, (m + 1) * 60])
    return out


class Model:
    """Aparelhos agrupados (principal + MACs juntados) e pessoas, lidos uma vez por pedido."""

    def __init__(self, db):
        self.devs = device_rows(db)
        self.people = {r[0]: r[1] for r in db.execute("SELECT id, name FROM people ORDER BY name COLLATE NOCASE")}
        self.canon = canon_map(self.devs)
        self.groups = {}
        for mac in sorted(self.devs):
            self.groups.setdefault(self.canon[mac], []).append(mac)

    def main(self, mac):
        return self.devs.get(self.canon.get(mac, mac))

    def counted(self, mac):
        m = self.main(mac)
        return m is not None and not m["hidden"]

    def person_of(self, mac):
        m = self.main(mac)
        return m["person_id"] if m and m["person_id"] in self.people else None

    def macs(self, mains):
        return [m for c in mains for m in self.groups.get(c, [])]

    def info(self, c):
        """Resumo do aparelho principal somando os MACs juntados (online se qualquer um estiver)."""
        d = self.devs[c]
        members = [self.devs[m] for m in self.groups[c]]
        on = [m for m in members if m["online"]]
        latest = max(members, key=lambda m: m["last_seen"] or 0)
        firsts = [m["first_seen"] for m in members if m["first_seen"]]
        return dict(d, name=name_of(d), ip=(on[0] if on else latest)["ip"], online=bool(on),
                    last_seen=latest["last_seen"], first_seen=min(firsts) if firsts else None,
                    private_mac=is_private_mac(c), person=self.people.get(d["person_id"]),
                    members=[{"mac": m["mac"], "ip": m["ip"], "online": m["online"],
                              "private_mac": is_private_mac(m["mac"])} for m in members if m["mac"] != c])


def activity_by(db, model, m0, m1=None, by="device", only=None):
    """{chave: {minuto: (categoria, app)}}: o mesmo minuto em dois MACs do mesmo aparelho (ou da mesma pessoa)
    conta uma vez. by: 'device' (principal) ou 'person'. only: limita a esses MACs (inclui infraestrutura)."""
    sql = "SELECT mac, minute, cat, app FROM activity WHERE minute >= ?" + (" AND minute < ?" if m1 else "")
    out = {}
    for mac, minute, cat, app in db.execute(sql, (m0, m1) if m1 else (m0,)).fetchall():
        if only is not None:
            if mac not in only:
                continue
        elif not model.counted(mac):
            continue
        key = model.canon.get(mac, mac) if by == "device" else model.person_of(mac)
        if key is not None:
            out.setdefault(key, {}).setdefault(minute, (cat, app))
    return {k: {m: mins[m] for m in in_use(mins)} for k, mins in out.items()}


USE_WINDOW, USE_MIN = 5, 4      # uso de verdade: pelo menos 4 minutos com consultas em ±5 minutos


def in_use(minutes):
    """Minutos que fazem parte de um uso de verdade. Apps sincronizam sozinhos a madrugada inteira (uma consulta
    a cada 10–20 min); quem está usando gera minutos seguidos. Calibrado com dados reais de uma casa."""
    s = sorted(minutes)
    return {m for m in s if bisect_right(s, m + USE_WINDOW) - bisect_left(s, m - USE_WINDOW) >= USE_MIN}


def query_totals(db, macs, days):
    if not macs:
        return 0, 0
    return db.execute("SELECT COALESCE(SUM(queries), 0), COALESCE(SUM(blocked), 0) FROM hourly WHERE day IN (%s) "
                      "AND mac IN (%s)" % (marks(days), marks(macs)), days + macs).fetchone()


def top_domains(db, model, macs, days, field="queries", limit=15, exclude=("system", "ads")):
    """Sites somados por domínio, com quantos aparelhos (principais) acessaram."""
    if not macs:
        return []
    col = "queries" if field == "queries" else "blocked"
    agg = {}
    for dom, cat, mac, n in db.execute(
            "SELECT domain, cat, mac, SUM(%s) FROM domains WHERE day IN (%s) AND mac IN (%s) %s GROUP BY domain, mac"
            % (col, marks(days), marks(macs), "AND cat NOT IN (%s)" % marks(exclude) if exclude else ""),
            days + macs + list(exclude or ())).fetchall():
        if not n:
            continue
        a = agg.setdefault(dom, {"domain": dom, "cat": cat, field: 0, "devices": set()})
        a[field] += n
        a["devices"].add(model.canon.get(mac, mac))
    rows = sorted(agg.values(), key=lambda a: -a[field])[:limit]
    return [dict(a, devices=len(a["devices"])) for a in rows]


def top_apps(db, macs, days, minute_values=(), limit=8):
    """Apps por minutos de uso (quando há) e por consultas (sempre há, inclusive no histórico antigo).
    minute_values: [(categoria, app), ...] de cada minuto de uso."""
    if not macs:
        return []
    apps = {}
    for dom, n in db.execute("SELECT domain, SUM(queries) FROM domains WHERE day IN (%s) AND mac IN (%s) GROUP BY domain"
                             % (marks(days), marks(macs)), days + macs).fetchall():
        app = app_of(dom)
        if app:
            apps.setdefault(app, {"app": app, "queries": 0, "minutes": 0})["queries"] += n or 0
    for cat, app in minute_values:
        if app:
            apps.setdefault(app, {"app": app, "queries": 0, "minutes": 0})["minutes"] += 1
    return sorted(apps.values(), key=lambda a: (-a["minutes"], -a["queries"]))[:limit]


def clock(minute_of_usage_day):
    """Minutos desde as 5h → 'HH:MM'."""
    m = (int(minute_of_usage_day) + DAY_START) % 1440
    return "%02d:%02d" % (m // 60, m % 60)


def median(values):
    s = sorted(values)
    if not s:
        return None
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def usage_summary(mins, night_from, night_to):
    """Resumo de um conjunto de minutos de uso {minuto: (cat, app)}: categorias, horários, rotina e recordes."""
    cats, apps, hours, by_day, work_day = Counter(), Counter(), [0] * 24, {}, {}
    night = 0
    for minute, (cat, app) in mins.items():
        t = datetime.fromtimestamp(minute * 60)
        cats[cat] += 1
        if app:
            apps[app] += 1
        hours[t.hour] += 1
        if night_from <= t.hour < night_to:
            night += 1
        shifted = t - timedelta(minutes=DAY_START)
        mod = shifted.hour * 60 + shifted.minute
        by_day.setdefault(shifted.date(), []).append(mod)
        if cat == "work":
            work_day.setdefault(shifted.date(), []).append(mod)
    starts = [min(v) for v in by_day.values()]
    ends = [max(v) for v in by_day.values()]
    streak, best = None, (0, None)
    for m in sorted(mins):
        if streak and m - streak[1] <= STREAK_GAP:
            streak = (streak[0], m)
        else:
            streak = (m, m)
        length = streak[1] - streak[0] + 1
        if length > best[0]:
            best = (length, streak[0] * 60)
    peak = max(range(24), key=lambda h: hours[h]) if mins else None
    return {
        "minutes": len(mins), "days_active": len(by_day),
        "per_day": len(mins) / float(len(by_day)) if by_day else 0,
        "categories": [{"cat": c, "minutes": n} for c, n in cats.most_common()],
        "apps": [{"app": a, "minutes": n} for a, n in apps.most_common(5)],
        "hours": hours, "peak_hour": peak, "night_minutes": night,
        "start": clock(median(starts)) if starts else None, "end": clock(median(ends)) if ends else None,
        "start_m": median(starts), "end_m": median(ends), "latest_m": max(ends) if ends else None,
        "work_minutes": cats.get("work", 0), "work_days": len(work_day),
        "work_start": clock(median([min(v) for v in work_day.values()])) if work_day else None,
        "work_end": clock(median([max(v) for v in work_day.values()])) if work_day else None,
        "streak_minutes": best[0], "streak_start": best[1],
    }


# Títulos da casa: cada um vai para quem tem o maior (ou menor) valor, se houver pelo menos duas pessoas com uso.
TITLES = [
    ("work", lambda p: p["work_minutes"], 30, max),
    ("social", lambda p: p["cat_minutes"].get("social", 0), 30, max),
    ("video", lambda p: p["cat_minutes"].get("video", 0), 30, max),
    ("games", lambda p: p["cat_minutes"].get("games", 0), 15, max),
    ("owl", lambda p: p["latest_m"], 0, max),
    ("early", lambda p: p["start_m"], 0, min),
    ("marathon", lambda p: p["streak_minutes"], 60, max),
    ("tracked", lambda p: p["blocked_pct"] if p["queries"] >= 500 else None, 0, max),
    ("home", lambda p: p["home_s"], 3600, max),
]


def award_titles(people):
    active = [p for p in people if p["minutes"]]
    if len(active) < 2:
        return
    for code, value, minimum, pick in TITLES:
        cands = [(value(p), p) for p in active if value(p) is not None and (pick is min or value(p) >= minimum)]
        if cands:
            best = pick(cands, key=lambda c: c[0])[1]
            best["titles"].append(code)


def home_seconds(db, macs, t0, t1, now):
    """Tempo em casa: união das sessões dos celulares e relógios da pessoa (eles saem de casa junto com ela)."""
    if not macs:
        return 0
    rows = db.execute("SELECT start_ts, COALESCE(end_ts, ?) FROM presence WHERE mac IN (%s) AND COALESCE(end_ts, ?) > ? "
                      "AND start_ts < ?" % marks(macs), [now] + macs + [now, t0, t1]).fetchall()
    return sum(b - a for a, b in merge_intervals([(max(a, t0), min(b, t1)) for a, b in rows if b > a]))


def people_summary(db, model, t0, t1, days, cfg):
    """Estatísticas por pessoa no intervalo, com os títulos da casa e os aparelhos ainda sem dono."""
    m0, m1 = int(t0 // 60), int(t1 // 60) + 1
    act = activity_by(db, model, m0, m1, by="person")
    nf, nt = int(cfg["night_from"]), int(cfg["night_to"])
    now = time.time()
    mains_by_person = {}
    for c in model.groups:
        d = model.devs[c]
        if not d["hidden"] and d["person_id"] in model.people:
            mains_by_person.setdefault(d["person_id"], []).append(c)
    out = []
    for pid, name in model.people.items():
        mains = mains_by_person.get(pid, [])
        macs = model.macs(mains)
        mins = act.get(pid, {})
        s = usage_summary(mins, nf, nt)
        q, b = query_totals(db, macs, days)
        mobile = model.macs([c for c in mains if model.devs[c]["kind"] in ("phone", "watch")])
        apps = top_apps(db, macs, days, mins.values(), limit=5)
        s.update(id=pid, name=name, queries=q, blocked=b, blocked_pct=100.0 * b / q if q else 0,
                 cat_minutes=dict((c["cat"], c["minutes"]) for c in s["categories"]),
                 apps=apps, sites=top_domains(db, model, macs, days, limit=5, exclude=("system", "ads", "other")),
                 home_s=home_seconds(db, mobile, t0, t1, now) if mobile else None,
                 devices=[{"mac": c, "name": name_of(model.devs[c]), "kind": model.devs[c]["kind"],
                           "online": model.info(c)["online"]} for c in mains],
                 titles=[])
        out.append(s)
    award_titles(out)
    out.sort(key=lambda p: -p["minutes"])
    unassigned = [{"mac": c, "name": name_of(model.devs[c]), "kind": model.devs[c]["kind"]}
                  for c in model.groups if not model.devs[c]["hidden"] and model.devs[c]["person_id"] not in model.people]
    return out, unassigned


def people_stats(db, key, cfg):
    t0, t1, days = period_range(key)
    model = Model(db)
    people, unassigned = people_summary(db, model, t0, t1, days, cfg)
    return {"period": key, "from": t0, "to": t1, "days": days, "people": people, "unassigned": unassigned}


def devices_list(db, cfg):
    t0, t1, days = period_range("today")
    model = Model(db)
    act = activity_by(db, model, int(t0 // 60))
    queries = {}
    for mac, q, b in db.execute("SELECT mac, SUM(queries), SUM(blocked) FROM hourly WHERE day=? GROUP BY mac",
                                (days[0],)).fetchall():
        tot = queries.setdefault(model.canon.get(mac, mac), [0, 0])
        tot[0] += q or 0
        tot[1] += b or 0
    out = []
    for c in model.groups:
        mins = act.get(c, {})
        cats = Counter(cat for cat, _ in mins.values())
        apps = Counter(app for _, app in mins.values() if app)
        q, b = queries.get(c, (0, 0))
        out.append(dict(model.info(c), today_minutes=len(mins), today_queries=q, today_blocked=b,
                        top_cat=cats.most_common(1)[0][0] if cats else None,
                        top_app=apps.most_common(1)[0][0] if apps else None))
    out.sort(key=lambda x: (x["hidden"], not x["online"], -x["today_minutes"], -(x["last_seen"] or 0)))
    return out


def overview(db, key, cfg):
    t0, t1, days = period_range(key)
    model = Model(db)
    act = activity_by(db, model, int(t0 // 60))
    nf, nt = int(cfg["night_from"]), int(cfg["night_to"])
    usage, night, hours, cats = [], [], [0] * 24, Counter()
    all_minutes = {}
    for c, mins in act.items():
        d = model.devs[c]
        n_night = 0
        for minute, (cat, app) in mins.items():
            h = datetime.fromtimestamp(minute * 60).hour
            hours[h] += 1
            cats[cat] += 1
            n_night += 1 if nf <= h < nt else 0
            all_minutes[(c, minute)] = (cat, app)
        usage.append({"mac": c, "name": name_of(d), "kind": d["kind"], "minutes": len(mins)})
        if n_night:
            night.append({"mac": c, "name": name_of(d), "kind": d["kind"], "minutes": n_night})
    usage.sort(key=lambda u: -u["minutes"])
    night.sort(key=lambda u: -u["minutes"])
    macs = [m for m in model.devs if model.counted(m)]
    q, b = query_totals(db, macs, days)
    new_devices = [{"mac": c, "name": name_of(model.devs[c]), "kind": model.devs[c]["kind"],
                    "first_seen": model.info(c)["first_seen"]}
                   for c in model.groups if not model.devs[c]["hidden"] and (model.info(c)["first_seen"] or 0) >= t0]
    events = []
    for ts, k, mac, detail in db.execute("SELECT ts, kind, mac, detail FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT 30",
                                         (t0,)).fetchall():
        d = model.main(mac)
        events.append({"ts": ts, "kind": k, "mac": model.canon.get(mac, mac), "detail": detail,
                       "name": name_of(d) if d else (detail or mac)})
    return {"period": key, "from": t0, "to": t1, "days": days,
            "totals": {"queries": q, "blocked": b, "active_devices": len(usage), "new_devices": len(new_devices),
                       "minutes": sum(u["minutes"] for u in usage)},
            "usage": usage, "categories": [{"cat": c, "minutes": n} for c, n in cats.most_common()], "hours": hours,
            "night": night, "night_from": nf, "night_to": nt,
            "apps": top_apps(db, macs, days, all_minutes.values()),
            "top_domains": top_domains(db, model, macs, days), "blocked": top_domains(db, model, macs, days, "blocked", 10, ()),
            "new_devices": new_devices, "events": events}


def device_detail(db, mac, key, cfg):
    model = Model(db)
    if mac not in model.devs:
        return None
    c = model.canon[mac]
    members = model.groups[c]
    d = model.info(c)
    t0, t1, days = period_range(key)
    now = time.time()
    m0 = int(t0 // 60)
    sess = []
    for s, e, mm in db.execute("SELECT start_ts, end_ts, mac FROM presence WHERE mac IN (%s) AND COALESCE(end_ts, ?) > ?"
                               % marks(members), members + [now, t0]).fetchall():
        if e is None:
            e = now if model.devs[mm]["online"] else (model.devs[mm]["last_seen"] or s)
        sess.append((s, e))
    sessions = merge_intervals(sess)
    mins = activity_by(db, model, m0, only=set(members)).get(c, {})
    minutes = sorted(mins)
    day_rows = []
    for day in days:
        ds = datetime.strptime(day, "%Y-%m-%d").timestamp()
        de = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).timestamp()
        on = [[max(s, ds), min(e, de)] for s, e in sessions if e > ds and s < de]
        act = [m for m in minutes if ds <= m * 60 < de]
        day_rows.append({"day": day, "start": ds, "end": de, "online": on, "active": merge_minutes(act),
                         "minutes": len(act), "online_s": sum(b - a for a, b in on)})
    hours = [0] * 24
    for m in minutes:
        hours[datetime.fromtimestamp(m * 60).hour] += 1
    cats = Counter(cat for cat, _ in mins.values())
    q, b = query_totals(db, members, days)
    # aparelhos com que este pode ser juntado: os outros principais
    candidates = sorted(({"mac": o, "name": name_of(model.devs[o])} for o in model.groups if o != c),
                        key=lambda x: x["name"].lower())
    return {"device": dict(d, is_member=mac != c), "period": key, "from": t0, "to": t1, "now": now,
            "totals": {"minutes": len(minutes), "online_s": sum(r["online_s"] for r in day_rows), "queries": q, "blocked": b},
            "days": day_rows, "hours": hours, "categories": [{"cat": k, "minutes": n} for k, n in cats.most_common()],
            "apps": top_apps(db, members, days, mins.values(), limit=6),
            "domains": device_domains(db, members, days),
            "blocked": top_domains(db, model, members, days, "blocked", 15, ()),
            "people": [{"id": i, "name": n} for i, n in model.people.items()],
            "candidates": candidates}


def device_domains(db, macs, days, limit=40):
    return [{"domain": dm, "cat": c, "queries": q, "blocked": b} for dm, c, q, b in db.execute(
        "SELECT domain, cat, SUM(queries) AS q, SUM(blocked) FROM domains WHERE mac IN (%s) AND day IN (%s) "
        "GROUP BY domain ORDER BY q DESC LIMIT %d" % (marks(macs), marks(days), limit), macs + days).fetchall()]


def wrapped(db, month, cfg):
    """O mês da casa em números: totais, recordes, apps e o resumo de cada pessoa."""
    t0, t1, days = month_range(month)
    model = Model(db)
    m0, m1 = int(t0 // 60), int(t1 // 60) + 1
    act = activity_by(db, model, m0, m1)
    macs = [m for m in model.devs if model.counted(m)]
    house = {}
    for c, mins in act.items():
        for minute, v in mins.items():
            house[(c, minute)] = v
    by_day, hours, cats = Counter(), [0] * 24, Counter()
    for (c, minute), (cat, app) in house.items():
        t = datetime.fromtimestamp(minute * 60)
        by_day[t.strftime("%Y-%m-%d")] += 1
        hours[t.hour] += 1
        cats[cat] += 1
    q, b = query_totals(db, macs, days)
    sites = db.execute("SELECT COUNT(DISTINCT domain) FROM domains WHERE day IN (%s) AND mac IN (%s)"
                       % (marks(days), marks(macs)), days + macs).fetchone()[0] if macs else 0
    people, _ = people_summary(db, model, t0, t1, days, cfg)
    busiest = by_day.most_common(1)[0] if by_day else None
    new = [name_of(model.devs[c]) for c in model.groups
           if not model.devs[c]["hidden"] and (model.info(c)["first_seen"] or 0) >= t0]
    records = {}
    with_streak = [p for p in people if p["streak_minutes"]]
    if with_streak:
        p = max(with_streak, key=lambda x: x["streak_minutes"])
        records["streak"] = {"name": p["name"], "minutes": p["streak_minutes"], "ts": p["streak_start"]}
    late = [p for p in people if p["latest_m"] is not None]
    if late:
        p = max(late, key=lambda x: x["latest_m"])
        records["latest"] = {"name": p["name"], "time": clock(p["latest_m"])}
    months = [r[0] for r in db.execute("SELECT DISTINCT substr(day, 1, 7) FROM hourly ORDER BY 1").fetchall()]
    net = internet_status(cfg)
    return {"month": datetime.fromtimestamp(t0).strftime("%Y-%m"), "from": t0, "to": t1, "days": len(days),
            "months": months, "minutes": len(house), "queries": q, "blocked": b, "sites": sites,
            "peak_hour": max(range(24), key=lambda h: hours[h]) if house else None, "hours": hours,
            "busiest_day": {"day": busiest[0], "minutes": busiest[1]} if busiest else None,
            "categories": [{"cat": c, "minutes": n} for c, n in cats.most_common(6)],
            "apps": top_apps(db, macs, days, house.values(), limit=5),
            "tracker": (top_domains(db, model, macs, days, "blocked", 1, ()) or [None])[0],
            "new_devices": new, "records": records, "people": people,
            "internet": {"outages": (net.get("d30") or {}).get("count"), "down_s": (net.get("d30") or {}).get("down_s")}
            if net.get("ok") else None}


def internet_status(cfg):
    """Resumo do down-again (se estiver rodando nesta máquina)."""
    url = (cfg.get("down_again_url") or "").rstrip("/")
    if not url:
        return {"enabled": False}
    try:
        st = fetch_json(url + "/api/status", timeout=3)
        gl = fetch_json(url + "/api/glance", timeout=3)
    except Exception:
        return {"enabled": True, "ok": False}
    speed = (st.get("speed") or {}).get("last") or {}
    return {"enabled": True, "ok": True, "state": st.get("state"), "since": st.get("since"),
            "h24": gl.get("h24"), "d7": gl.get("d7"), "d30": gl.get("d30"), "port": urlparse(url).port,
            "speed": {"ts": speed.get("ts"), "down": speed.get("down"), "up": speed.get("up")} if speed else None}


# --------------------------------------------------------------------------
# servidor web

# Só estes arquivos são servidos — nada de montar caminho a partir da URL.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/device": ("device.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/common.js": ("common.js", "application/javascript; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/device.js": ("device.js", "application/javascript; charset=utf-8"),
    "/wrapped": ("wrapped.html", "text/html; charset=utf-8"),
    "/wrapped.js": ("wrapped.js", "application/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
KINDS = ("phone", "tablet", "computer", "tv", "console", "watch", "speaker", "printer", "camera", "router", "other")
MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def host_allowed(host_header, extra):
    """Bloqueia DNS rebinding: só aceita IP, localhost, *.local, o nome desta máquina e allowed_hosts."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.rstrip(".")
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host == "localhost" or host.endswith(".local") or host in [h.lower() for h in extra]


def clean_text(value, size):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:size] or None


def parse_device_update(body):
    """Corpo do POST /api/device → só os campos enviados, validados (ValueError se inválido):
    mac (obrigatório), nickname, kind, person_id (número ou null), parent (MAC ou null) e hidden."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("body")
    mac = norm_mac(str(data.get("mac") or ""))
    if not mac or not MAC_RE.match(mac):
        raise ValueError("mac")
    out = {"mac": mac}
    if "nickname" in data:
        out["nickname"] = clean_text(data["nickname"], 40)
    if "kind" in data:
        kind = data["kind"] or None
        if kind is not None and kind not in KINDS:
            raise ValueError("kind")
        out["kind"] = kind
    if "person_id" in data:
        pid = data["person_id"]
        if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
            raise ValueError("person_id")
        out["person_id"] = pid
    if "parent" in data:
        parent = norm_mac(str(data["parent"])) if data["parent"] else None
        if data["parent"] and (not parent or parent == mac):
            raise ValueError("parent")
        out["parent"] = parent
    if "hidden" in data:
        out["hidden"] = 1 if data["hidden"] else 0
    return out


def parse_person_update(body):
    """Corpo do POST /api/person → {'id', 'name', 'delete'}: sem id cria, com id renomeia ou apaga."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("body")
    pid = data.get("id")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        raise ValueError("id")
    delete = bool(data.get("delete"))
    name = clean_text(data.get("name"), 30)
    if not delete and not name:
        raise ValueError("name")
    if delete and pid is None:
        raise ValueError("id")
    return {"id": pid, "name": name, "delete": delete}


def update_device(db, upd):
    """Aplica a edição de um aparelho. Juntar a outro: os MACs que já estavam juntados a este vão junto
    (fica sempre um nível só: principal → MACs)."""
    mac = upd["mac"]
    if not db.execute("SELECT 1 FROM devices WHERE mac=?", (mac,)).fetchone():
        return "not_found"
    if upd.get("person_id") is not None and not db.execute("SELECT 1 FROM people WHERE id=?", (upd["person_id"],)).fetchone():
        return "invalid"
    if upd.get("parent"):
        row = db.execute("SELECT parent FROM devices WHERE mac=?", (upd["parent"],)).fetchone()
        if not row:
            return "invalid"
        target = row[0] or upd["parent"]          # juntar a um MAC juntado = juntar ao principal dele
        if target == mac:
            return "invalid"
        upd["parent"] = target
        db.execute("UPDATE devices SET parent=? WHERE parent=?", (target, mac))
    for col in ("nickname", "kind", "person_id", "parent", "hidden"):
        if col in upd:
            db.execute("UPDATE devices SET %s=? WHERE mac=?" % col, (upd[col], mac))
    return None


def update_person(db, upd):
    if upd["delete"]:
        db.execute("UPDATE devices SET person_id=NULL WHERE person_id=?", (upd["id"],))
        db.execute("DELETE FROM people WHERE id=?", (upd["id"],))
        return upd["id"]
    if upd["id"] is None:
        return db.execute("INSERT INTO people(name, created) VALUES(?, ?)", (upd["name"], time.time())).lastrowid
    db.execute("UPDATE people SET name=? WHERE id=?", (upd["name"], upd["id"]))
    return upd["id"]


class Handler(BaseHTTPRequestHandler):
    collector = None
    notifier = None
    cfg = None
    info = {}
    own_names = set()
    timeout = 30
    server_version = "who-is-home"
    sys_version = ""
    last_test = 0
    test_lock = threading.Lock()

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in list(SECURITY_HEADERS.items()) + list((extra or {}).items()):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def check_host(self):
        if host_allowed(self.headers.get("Host"), list(self.cfg.get("allowed_hosts") or []) + list(self.own_names)):
            return True
        self.send(403, tr("http.host"), "text/plain; charset=utf-8")
        return False

    def collector_status(self):
        st = dict(self.collector.status) if self.collector else {"adguard": "demo"}
        return st

    def do_GET(self):
        if not self.check_host():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        period = q.get("period", ["today"])[0]
        if period not in PERIODS:
            period = "today"
        if u.path.startswith("/api/"):
            db = connect()
            try:
                if u.path == "/api/now":
                    devs = devices_list(db, self.cfg)
                    return self.json({"now": time.time(), "online": sum(1 for d in devs if d["online"]),
                                      "total": len(devs), "status": self.collector_status()})
                if u.path == "/api/devices":
                    return self.json(devices_list(db, self.cfg))
                if u.path == "/api/overview":
                    return self.json(overview(db, period, self.cfg))
                if u.path == "/api/device":
                    mac = norm_mac(q.get("mac", [""])[0])
                    detail = device_detail(db, mac, period, self.cfg) if mac else None
                    return self.json(detail) if detail else self.json({"error": "not found"}, 404)
                if u.path == "/api/people":
                    return self.json(people_stats(db, period, self.cfg))
                if u.path == "/api/wrapped":
                    return self.json(wrapped(db, q.get("month", [""])[0], self.cfg))
                if u.path == "/api/internet":
                    return self.json(internet_status(self.cfg))
                if u.path == "/api/config":
                    return self.json({"port": self.cfg["port"], "host": self.info.get("host"), "ip": self.info.get("ip"),
                                      "adguard_url": self.cfg["adguard_url"], "language": LANG, "version": VERSION,
                                      "platform": PLATFORM, "ntfy": bool(self.cfg.get("ntfy_topic")),
                                      "offline_minutes": self.cfg["offline_minutes"], "kinds": list(KINDS)})
            finally:
                db.close()
            return self.send(404, "not found", "text/plain; charset=utf-8")
        self.static(u.path)

    def do_POST(self):
        if not self.check_host():
            return
        u = urlparse(self.path)
        if u.path not in ("/api/device", "/api/person", "/api/test-notify"):
            return self.send(404, "not found", "text/plain; charset=utf-8")
        # Cabeçalho próprio força preflight de CORS (que não respondemos): outro site não consegue disparar.
        if self.headers.get("X-Who-Is-Home") != "1":
            return self.json({"ok": False, "code": "refused"}, 403)
        if u.path == "/api/test-notify":
            return self.post_test()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 2048:
                raise ValueError("length")
            body = self.rfile.read(length)
            upd = parse_device_update(body) if u.path == "/api/device" else parse_person_update(body)
        except (ValueError, TypeError, AttributeError):
            return self.json({"ok": False, "code": "invalid"}, 400)
        db = connect()
        try:
            with WRITE:
                if u.path == "/api/person":
                    pid = update_person(db, upd)
                    db.commit()
                    return self.json({"ok": True, "id": pid})
                err = update_device(db, upd)
                if err:
                    db.rollback()
                    return self.json({"ok": False, "code": err}, 404 if err == "not_found" else 400)
                db.commit()
        finally:
            db.close()
        return self.json({"ok": True})

    def post_test(self):
        with Handler.test_lock:
            wait = 30 - (time.time() - Handler.last_test)
            if wait > 0:
                return self.json({"ok": False, "code": "cooldown", "wait": int(wait) + 1}, 429)
            Handler.last_test = time.time()
        if not self.notifier or not self.notifier.enabled:
            return self.json({"ok": False, "code": "disabled"})
        ok, err = self.notifier.send(tr("notify.test.title"), tr("notify.test.body"), ["white_check_mark"])
        return self.json({"ok": ok, "code": None if ok else "send_failed"})

    def static(self, path):
        if path not in STATIC_FILES:
            return self.send(404, "not found", "text/plain; charset=utf-8")
        name, ctype = STATIC_FILES[path]
        with open(os.path.join(STATIC, name), "rb") as f:
            self.send(200, f.read(), ctype)


class Server(ThreadingHTTPServer):
    # O padrão do Python é uma fila de 5 conexões: o navegador abre a página com ~10 pedidos de uma vez e o
    # macOS recusa o que passa disso (a página abria sem CSS de vez em quando).
    request_queue_size = 128
    daemon_threads = True


def serve(cfg, collector=None, notifier=None):
    host, ip = local_hostname(), local_ip()
    Handler.collector, Handler.notifier, Handler.cfg = collector, notifier, cfg
    Handler.info = {"host": host, "ip": ip}
    name = socket.gethostname().lower()
    Handler.own_names = {name, name.split(".")[0]}
    server = Server((cfg["bind"], cfg["port"]), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for addr in ("localhost", host, ip):
        if addr:
            log(tr("log.panel", url="http://%s:%d" % (addr, cfg["port"])))
    return server


# --------------------------------------------------------------------------
# comandos

def cmd_run(cfg):
    notifier = Notifier(cfg)
    collector = Collector(cfg, notifier)
    log(tr("log.started", os=PLATFORM))
    if not IS_MAC:
        log(tr("log.experimental", os=PLATFORM))
    serve(cfg, collector, notifier)
    threading.Thread(target=notifier.run, daemon=True).start()
    collector.start()
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        collector.stop_flag.set()
        log(tr("log.stopped"))


def ask(prompt, secret=False):
    try:
        return (getpass.getpass(prompt) if secret else input(prompt)).strip()
    except EOFError:
        return ""


def cmd_setup(cfg):
    print(tr("setup.intro", url=cfg["adguard_url"]))
    while True:
        user = ask(tr("setup.user"))
        password = ask(tr("setup.password"), secret=True)
        trial = dict(cfg, adguard_user=user, adguard_password=password)
        try:
            AdGuard(trial).get("/control/status", timeout=8)
            print(tr("setup.ok"))
            cfg["adguard_user"], cfg["adguard_password"] = user, password
            break
        except Exception as e:
            print(tr("setup.failed", err=error_text(e)))
            if ask(tr("setup.retry")).lower() in ("n", "no", "nao", "não", "否"):
                return
    if not cfg.get("ntfy_topic"):
        topic = ""
        da_cfg = os.path.join(os.path.dirname(BASE), "down-again", "dados", "config.json")
        try:
            with open(da_cfg, encoding="utf-8") as f:
                topic = json.load(f).get("ntfy_topic") or ""
        except (OSError, ValueError):
            topic = ""
        if topic and ask(tr("setup.ntfy_reuse", topic=topic)).lower() not in ("n", "no", "nao", "não", "否"):
            cfg["ntfy_topic"] = topic
        elif not topic:
            cfg["ntfy_topic"] = ask(tr("setup.ntfy_new"))
    save_config(cfg)
    print(tr("setup.saved", path=CONFIG_PATH))
    # já instalado: reinicia o serviço para ele ler o login novo
    if IS_MAC and os.path.exists(PLIST_PATH):
        run_cmd(["launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), PLIST_LABEL)], timeout=15)
    elif IS_LINUX and os.path.exists(SYSTEMD_PATH):
        run_cmd(["systemctl", "--user", "restart", SYSTEMD_UNIT], timeout=30)


def cmd_check(cfg):
    rows = []
    ag = AdGuard(cfg)
    if not ag.configured:
        rows.append((tr("check.adguard"), tr("check.not_set")))
    else:
        try:
            data = ag.querylog(limit=100)
            rows.append((tr("check.adguard"), tr("check.queries", n=len(data.get("data") or []))))
        except Exception as e:
            rows.append((tr("check.adguard"), "%s — %s" % (tr("check.failed"), error_text(e))))
    ip, prefix, mac = own_interface()
    if ip:
        replies, arp = sweep(ip, prefix)
        rows.append((tr("check.scan"), "%s/%s · %s" % (ip, prefix, tr("check.devices", n=len(replies)))))
    else:
        rows.append((tr("check.scan"), tr("check.failed")))
    net = internet_status(cfg)
    rows.append((tr("check.down_again"), tr("check.off") if not net["enabled"] else
                 ("%s (%s)" % (tr("check.ok"), net.get("state")) if net.get("ok") else tr("check.failed"))))
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print("%s : %s" % (label.ljust(width), value))


def print_installed(cfg, how, logs):
    print(tr("install.done", how=how))
    print(tr("install.panel", url="http://%s:%d" % (local_hostname() or local_ip() or "localhost", cfg["port"])))
    print(tr("install.log", log=logs))


# --- macOS: LaunchAgent ---

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string><string>{script}</string>
  </array>
  <key>WorkingDirectory</key><string>{base}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def install_mac(cfg):
    home = os.path.expanduser("~")
    for protected in ("Desktop", "Documents", "Downloads", "Mesa", "Documentos"):
        if BASE.startswith(os.path.join(home, protected) + os.sep):
            print(tr("install.protected", folder=protected))
            return
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    if os.path.exists(PLIST_PATH):
        run_cmd(["launchctl", "unload", "-w", PLIST_PATH])
    with open(PLIST_PATH, "w", encoding="utf-8") as f:
        f.write(PLIST.format(label=PLIST_LABEL, python=xml_escape(sys.executable),
                             script=xml_escape(os.path.abspath(__file__)), base=xml_escape(BASE), log=xml_escape(LOG_PATH)))
    code, _ = run_cmd(["launchctl", "load", "-w", PLIST_PATH])
    if code != 0:
        print(tr("install.launchd_failed", path=PLIST_PATH))
        return
    print_installed(cfg, tr("install.how_mac"), LOG_PATH)


def uninstall_mac():
    if not os.path.exists(PLIST_PATH):
        return False
    run_cmd(["launchctl", "unload", "-w", PLIST_PATH])
    os.remove(PLIST_PATH)
    return True


# --- Linux (experimental): serviço de usuário do systemd ---

SYSTEMD_UNIT = "who-is-home.service"
SYSTEMD_PATH = os.path.expanduser("~/.config/systemd/user/" + SYSTEMD_UNIT)
UNIT = """[Unit]
Description=who-is-home - home network devices and usage
After=network-online.target

[Service]
ExecStart={python} {script}
WorkingDirectory={base}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def systemd_quote(s):
    # aspas para espaços; '%' é especificador no systemd e precisa virar '%%'
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def install_linux(cfg):
    if not shutil.which("systemctl"):
        print(tr("install.no_systemd", cmd="%s %s" % (sys.executable, os.path.abspath(__file__))))
        return
    os.makedirs(os.path.dirname(SYSTEMD_PATH), exist_ok=True)
    with open(SYSTEMD_PATH, "w", encoding="utf-8") as f:
        f.write(UNIT.format(python=systemd_quote(sys.executable), script=systemd_quote(os.path.abspath(__file__)),
                            base=BASE.replace("%", "%%")))
    for args in (["daemon-reload"], ["enable", SYSTEMD_UNIT], ["restart", SYSTEMD_UNIT]):
        code, _ = run_cmd(["systemctl", "--user"] + args, timeout=30)
        if code != 0:
            print(tr("install.systemctl_failed", cmd=" ".join(args)))
            return
    print_installed(cfg, tr("install.how_linux"), "journalctl --user -u %s -f" % SYSTEMD_UNIT)


def uninstall_linux():
    if not os.path.exists(SYSTEMD_PATH):
        return False
    run_cmd(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], timeout=30)
    os.remove(SYSTEMD_PATH)
    run_cmd(["systemctl", "--user", "daemon-reload"], timeout=30)
    return True


def cmd_install(cfg):
    if IS_MAC:
        install_mac(cfg)
    elif IS_LINUX:
        install_linux(cfg)
    else:
        print(tr("install.unsupported", os=PLATFORM))


def cmd_uninstall(cfg):
    removed = {"macOS": uninstall_mac, "Linux": uninstall_linux}.get(PLATFORM, lambda: False)()
    print(tr("uninstall.done", data=DATA) if removed else tr("uninstall.none"))


def main():
    ap = argparse.ArgumentParser(description="who-is-home: home network devices, usage and lookups with a web dashboard.")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "setup", "check", "install", "uninstall"])
    ap.add_argument("--port", type=int, help="dashboard port (default: config.json)")
    args = ap.parse_args()
    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
    {"run": cmd_run, "setup": cmd_setup, "check": cmd_check, "install": cmd_install,
     "uninstall": cmd_uninstall}[args.cmd](cfg)


if __name__ == "__main__":
    main()

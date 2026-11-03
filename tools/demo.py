#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Painel de demonstração com 7 dias de dados simulados (pasta temporária, nunca toca em dados/).
Não varre a rede, não lê o AdGuard e não manda avisos.

    python3 tools/demo.py            → http://localhost:8767
"""
import os
import random
import sys
import tempfile
import time

os.environ["WHOISHOME_DATA"] = tempfile.mkdtemp(prefix="who-is-home-demo-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import who_is_home as wh  # noqa: E402

PORT = 8767
# (mac, ip, nome descoberto, apelido, tipo, horas de uso típicas, sites preferidos)
DEVICES = [
    ("a4:83:e7:10:20:01", "192.168.0.21", "Anas-iPhone", "iPhone da Ana", "phone", [(7, 8), (12, 13), (19, 23)],
     ["instagram.com", "whatsapp.net", "tiktok.com", "youtube.com", "spotify.com"]),
    ("3c:22:fb:10:20:02", "192.168.0.22", "MacBook-Pro", None, "computer", [(9, 12), (14, 18)],
     ["github.com", "slack.com", "google.com", "notion.so", "zoom.us"]),
    ("da:11:22:33:44:03", "192.168.0.23", "android-7f3a", "Celular do João", "phone", [(10, 12), (15, 18), (21, 24), (0, 2)],
     ["roblox.com", "youtube.com", "tiktok.com", "discord.com", "whatsapp.net"]),
    ("a8:23:fe:10:20:04", "192.168.0.24", "LGwebOSTV", "TV da sala", "tv", [(20, 23)],
     ["netflix.com", "youtube.com", "globoplay.globo.com"]),
    ("f0:99:bf:10:20:05", "192.168.0.25", "iPad", None, "tablet", [(17, 20)],
     ["youtube.com", "roblox.com", "netflix.com"]),
    ("fc:aa:bb:cc:dd:f3", "192.168.0.202", "HPAABBCCDDF3", None, "printer", [], []),
    ("00:d8:61:10:20:07", "192.168.0.27", "DESKTOP-8KQ2", "PC do escritório", "computer", [(8, 12), (13, 17)],
     ["office.com", "outlook.com", "google.com", "uol.com.br", "mercadolivre.com.br"]),
]
SYSTEM = ["icloud.com", "apple.com", "googleapis.com", "gstatic.com", "doubleclick.net", "app-measurement.com"]


def fill(db):
    rnd = random.Random(7)
    now = time.time()
    start = wh.midnight(now) - 6 * 86400
    entries = []
    for mac, ip, host, nick, kind, hours, sites in DEVICES:
        first = start - rnd.randint(0, 20) * 86400 if mac != DEVICES[4][0] else now - 2 * 86400
        db.execute("INSERT INTO devices(mac, ip, hostname, name_source, nickname, kind, first_seen, last_seen, online) "
                   "VALUES(?,?,?,?,?,?,?,?,0)", (mac, ip, host, "mdns", nick, kind, first, first))
        for day in range(7):
            base = start + day * 86400
            for a, b in hours:
                s = base + a * 3600 + rnd.randint(-900, 900)
                e = min(base + b * 3600 + rnd.randint(-900, 900), now)
                if s >= now:
                    continue
                db.execute("INSERT INTO presence(mac, start_ts, end_ts) VALUES(?,?,?)", (mac, s - 600, e + 600))
                t = s
                while t < e:
                    burst = rnd.randint(3, 12)
                    for _ in range(burst):
                        name = rnd.choice(sites) if rnd.random() < 0.8 else rnd.choice(SYSTEM)
                        entries.append({"ts": t + rnd.random() * 50, "ip": ip, "mac": mac, "name": "www." + name,
                                        "blocked": name in ("doubleclick.net", "app-measurement.com")})
                    t += rnd.choice([60, 60, 60, 120, 300])
            if not hours:      # impressora: fica ligada o dia todo, só tráfego de sistema
                db.execute("INSERT INTO presence(mac, start_ts, end_ts) VALUES(?,?,?)", (mac, base, min(base + 86400, now)))
    wh.ingest(db, entries, 2)
    for mac, ip, host, nick, kind, hours, sites in DEVICES:
        last = db.execute("SELECT MAX(COALESCE(end_ts, 0)) FROM presence WHERE mac=?", (mac,)).fetchone()[0] or start
        online = 1 if rnd.random() < 0.6 or kind == "printer" else 0
        db.execute("UPDATE devices SET last_seen=?, online=? WHERE mac=?", (now if online else last, online, mac))
        if online:
            db.execute("UPDATE presence SET end_ts=NULL WHERE id=(SELECT MAX(id) FROM presence WHERE mac=?)", (mac,))
    db.execute("INSERT INTO events(ts, kind, mac, detail) VALUES(?,?,?,?)", (now - 2 * 86400, "new", DEVICES[4][0], DEVICES[4][1]))
    db.commit()


def main():
    cfg = wh.load_config()
    cfg.update(port=PORT, down_again_url="", ntfy_topic="")
    db = wh.connect()
    fill(db)
    db.close()
    wh.serve(cfg)
    print("demo: http://localhost:%d  (dados em %s)" % (PORT, wh.DATA))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

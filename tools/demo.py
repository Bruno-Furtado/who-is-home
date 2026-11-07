#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Painel de demonstração com 7 dias de dados simulados (pasta temporária, nunca toca em dados/).
Não varre a rede, não lê o AdGuard, não fala com o down-again e não manda avisos.

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
                db.execute("INSERT INTO presence(mac, start_ts, end_ts) VALUES(?,?,?)", (mac, s - 600, min(e + 600, now)))
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
    hour = time.localtime(now).tm_hour
    for i, (mac, ip, host, nick, kind, hours, sites) in enumerate(DEVICES):
        last = db.execute("SELECT MAX(COALESCE(end_ts, 0)) FROM presence WHERE mac=?", (mac,)).fetchone()[0] or start
        # online: impressora, quem está no horário de uso agora e metade dos outros (a lista fica variada)
        online = 1 if kind == "printer" or any(a <= hour < b for a, b in hours) or i % 2 == 0 else 0
        db.execute("UPDATE devices SET last_seen=?, online=? WHERE mac=?", (now if online else last, online, mac))
        if online:
            db.execute("UPDATE presence SET end_ts=NULL WHERE id=(SELECT id FROM presence WHERE mac=? "
                       "ORDER BY start_ts DESC LIMIT 1)", (mac,))
    db.execute("INSERT INTO events(ts, kind, mac, detail) VALUES(?,?,?,?)", (now - 2 * 86400, "new", DEVICES[4][0], DEVICES[4][1]))
    # pessoas, o cabo do MacBook juntado ao Wi-Fi dele e o roteador como infraestrutura
    ana = wh.update_person(db, {"id": None, "name": "Ana", "delete": False})
    joao = wh.update_person(db, {"id": None, "name": "João", "delete": False})
    for i, pid in ((0, ana), (1, ana), (2, joao), (4, joao), (6, ana)):
        wh.update_device(db, {"mac": DEVICES[i][0], "person_id": pid})
    db.execute("INSERT INTO devices(mac, ip, hostname, name_source, kind, first_seen, last_seen, online) "
               "VALUES('3c:22:fb:10:20:99', '192.168.0.31', 'MacBook-Pro', 'mdns', 'computer', ?, ?, 0)", (start, now - 7200))
    wh.update_device(db, {"mac": "3c:22:fb:10:20:99", "parent": DEVICES[1][0]})
    db.execute("INSERT INTO devices(mac, ip, nickname, kind, first_seen, last_seen, online, hidden) "
               "VALUES('06:02:aa:bb:0c:1e', '192.168.0.1', 'Roteador', 'router', ?, ?, 1, 1)", (start - 30 * 86400, now))
    db.commit()


def fake_internet(cfg):
    """Cartão da internet sem precisar do down-again rodando."""
    now = time.time()
    return {"enabled": True, "ok": True, "state": "up", "since": now - 9 * 3600, "h24": {"count": 1, "down_s": 92},
            "d7": {"count": 3, "down_s": 610}, "port": None, "speed": {"ts": now - 3600, "down": 512.4, "up": 248.9}}


def main():
    cfg = wh.load_config()
    cfg.update(port=PORT, ntfy_topic="")
    wh.internet_status = fake_internet
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

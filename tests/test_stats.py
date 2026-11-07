# -*- coding: utf-8 -*-
"""
Gravação das consultas (ingest), presença e relatórios num banco temporário.

    python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("WHOISHOME_DATA", tempfile.mkdtemp(prefix="who-is-home-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import who_is_home as wh  # noqa: E402

MAC = "a4:83:e7:10:20:01"


class FakeNotifier:
    enabled = True

    def __init__(self):
        self.sent = []

    def queue(self, db, title, body, tag):
        self.sent.append(title)


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(wh.DATA.startswith(tempfile.gettempdir()) or "test" in wh.DATA)
        if os.path.exists(wh.DB_PATH):
            os.remove(wh.DB_PATH)
        self.cfg = wh.load_config()
        self.db = wh.connect()
        self.notifier = FakeNotifier()
        self.col = wh.Collector(self.cfg, self.notifier)

    def tearDown(self):
        self.db.close()

    def queries(self, start, minutes, name="www.youtube.com", per_minute=3, blocked=False):
        return [{"ts": start + m * 60 + i, "ip": "192.168.0.21", "mac": MAC, "name": name, "blocked": blocked}
                for m in range(minutes) for i in range(per_minute)]

    def test_ingest_and_overview(self):
        now = time.time()
        start = max(wh.midnight(now), now - 3 * 3600)
        entries = self.queries(start, 30) + self.queries(start, 30, name="doubleclick.net", blocked=True) + \
            self.queries(start + 1800, 10, name="gateway.icloud.com")
        self.col.mark_seen(self.db, MAC, "192.168.0.21", start)
        wh.ingest(self.db, entries, 2, self.col)
        self.db.commit()
        o = wh.overview(self.db, "today", self.cfg)
        self.assertEqual(o["totals"]["queries"], len(entries))
        self.assertEqual(o["totals"]["blocked"], 90)
        self.assertEqual(o["usage"][0]["minutes"], 30)          # sistema e bloqueados não contam como uso
        self.assertEqual(o["categories"], [{"cat": "video", "minutes": 30}])
        self.assertEqual(o["top_domains"][0]["domain"], "youtube.com")
        self.assertEqual(o["blocked"][0]["domain"], "doubleclick.net")
        self.assertEqual(sum(o["hours"]), 30)
        d = wh.device_detail(self.db, MAC, "today", self.cfg)
        self.assertEqual(d["totals"]["minutes"], 30)
        self.assertEqual(sum(len(day["active"]) for day in d["days"]), 1)    # 30 minutos seguidos = 1 trecho

    def test_ingest_accumulates(self):
        start = wh.midnight(time.time()) + 60
        wh.ingest(self.db, self.queries(start, 1), 2)
        wh.ingest(self.db, self.queries(start, 1), 2)
        q = self.db.execute("SELECT queries FROM domains WHERE mac=?", (MAC,)).fetchone()[0]
        self.assertEqual(q, 6)

    def test_presence(self):
        now = time.time()
        self.col.mark_seen(self.db, MAC, "192.168.0.21", now - 3600)
        self.assertEqual(self.notifier.sent, [])                 # primeira varredura não avisa
        wh.state_set(self.db, "bootstrapped", "1")
        self.col.mark_seen(self.db, "3c:22:fb:10:20:02", "192.168.0.22", now)
        self.assertEqual(len(self.notifier.sent), 1)
        self.col.close_stale(self.db, now)
        on = dict(self.db.execute("SELECT mac, online FROM devices").fetchall())
        self.assertEqual(on, {MAC: 0, "3c:22:fb:10:20:02": 1})
        end = self.db.execute("SELECT end_ts FROM presence WHERE mac=?", (MAC,)).fetchone()[0]
        self.assertAlmostEqual(end, now - 3600)
        self.col.mark_seen(self.db, MAC, "192.168.0.21", now)    # voltou: nova sessão
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM presence WHERE mac=?", (MAC,)).fetchone()[0], 2)

    def test_merge_minutes(self):
        self.assertEqual(wh.merge_minutes([10, 11, 12, 20]), [[600, 780], [1200, 1260]])

    def test_period(self):
        t0, t1, days = wh.period_range("7d")
        self.assertEqual(len(days), 7)
        self.assertEqual(days[-1], wh.day_str(time.time()))
        t0, t1, days = wh.month_range("2026-02", now=time.mktime((2026, 3, 10, 12, 0, 0, 0, 0, -1)))
        self.assertEqual((days[0], days[-1], len(days)), ("2026-02-01", "2026-02-28", 28))

    def test_in_use_ignores_background(self):
        # sincronização a cada 15 min (fundo) some; 10 minutos seguidos (uso) ficam
        background = {m: ("messaging", None) for m in range(0, 120, 15)}
        session = {m: ("social", None) for m in range(200, 210)}
        kept = wh.in_use(dict(list(background.items()) + list(session.items())))
        self.assertEqual(kept, set(range(200, 210)))

    def add(self, mac, ip):
        self.db.execute("INSERT INTO devices(mac, ip, first_seen, last_seen, online, hidden) VALUES(?,?,?,?,1,0)",
                        (mac, ip, time.time() - 3600, time.time()))

    def test_join_people_and_titles(self):
        # ontem às 10h: tudo no passado, qualquer que seja a hora em que o teste roda
        start = wh.midnight(time.time()) - 86400 + 10 * 3600
        wifi, cable, phone = MAC, "3c:22:fb:10:20:02", "da:11:22:33:44:03"
        for mac, ip in ((wifi, "192.168.0.21"), (cable, "192.168.0.22"), (phone, "192.168.0.23")):
            self.add(mac, ip)
        ana = wh.update_person(self.db, {"id": None, "name": "Ana", "delete": False})
        joao = wh.update_person(self.db, {"id": None, "name": "João", "delete": False})
        self.assertIsNone(wh.update_device(self.db, {"mac": cable, "parent": wifi, "person_id": ana}))
        self.assertIsNone(wh.update_device(self.db, {"mac": wifi, "person_id": ana}))
        self.assertIsNone(wh.update_device(self.db, {"mac": phone, "person_id": joao}))
        q = lambda mac, s, n, name: [dict(e, mac=mac) for e in self.queries(s, n, name=name)]
        # o mesmo minuto no cabo e no Wi-Fi conta uma vez só; João trabalha mais
        wh.ingest(self.db, q(wifi, start, 30, "www.instagram.com") + q(cable, start, 30, "www.instagram.com")
                  + q(phone, start, 20, "github.com") + q(phone, start + 3600, 25, "slack.com"), 2)
        self.db.commit()
        p = wh.people_stats(self.db, "7d", self.cfg)
        by = {x["name"]: x for x in p["people"]}
        self.assertEqual(by["Ana"]["minutes"], 30)
        self.assertEqual(by["João"]["work_minutes"], 45)
        self.assertIn("work", by["João"]["titles"])
        self.assertIn("social", by["Ana"]["titles"])
        self.assertEqual(by["Ana"]["apps"][0]["app"], "Instagram")
        devs = {d["mac"]: d for d in wh.devices_list(self.db, self.cfg)}
        self.assertNotIn(cable, devs)                              # juntado: aparece dentro do principal
        self.assertEqual([m["mac"] for m in devs[wifi]["members"]], [cable])
        detail = wh.device_detail(self.db, cable, "7d", self.cfg)
        self.assertEqual(detail["device"]["mac"], wifi)            # abrir pelo MAC juntado leva ao principal
        w = wh.wrapped(self.db, wh.day_str(start)[:7], self.cfg)
        self.assertEqual(w["minutes"], 75)
        self.assertEqual(w["apps"][0], {"app": "Instagram", "queries": 180, "minutes": 30})
        # juntar o principal a outro leva os MACs dele junto (um nível só)
        self.assertIsNone(wh.update_device(self.db, {"mac": wifi, "parent": phone}))
        parents = dict(self.db.execute("SELECT mac, parent FROM devices").fetchall())
        self.assertEqual((parents[wifi], parents[cable]), (phone, phone))
        self.assertEqual(wh.update_device(self.db, {"mac": phone, "parent": wifi}), "invalid")

    def test_hidden_left_out(self):
        start = wh.midnight(time.time()) + 60
        self.add(MAC, "192.168.0.21")
        wh.update_device(self.db, {"mac": MAC, "hidden": 1})
        wh.ingest(self.db, self.queries(start, 10), 2)
        o = wh.overview(self.db, "today", self.cfg)
        self.assertEqual((o["totals"]["minutes"], o["totals"]["queries"]), (0, 0))

    def test_parse_updates(self):
        u = wh.parse_device_update(b'{"mac": "6:2:aa:bb:c:1e", "person_id": 3, "parent": "aa:bb:cc:dd:ee:ff", "hidden": true}')
        self.assertEqual(u, {"mac": "06:02:aa:bb:0c:1e", "person_id": 3, "parent": "aa:bb:cc:dd:ee:ff", "hidden": 1})
        self.assertEqual(wh.parse_device_update(b'{"mac": "06:02:aa:bb:0c:1e"}'), {"mac": "06:02:aa:bb:0c:1e"})
        for bad in (b'{"mac": "06:02:aa:bb:0c:1e", "person_id": "1"}', b'{"mac": "06:02:aa:bb:0c:1e", "parent": "06:02:aa:bb:0c:1e"}',
                    b'[1]'):
            with self.assertRaises(ValueError):
                wh.parse_device_update(bad)
        self.assertEqual(wh.parse_person_update(b'{"name": " Ana\\n "}'), {"id": None, "name": "Ana", "delete": False})
        with self.assertRaises(ValueError):
            wh.parse_person_update(b'{"delete": true}')

    def test_migration_v2(self):
        self.add(MAC, "192.168.0.21")
        self.db.execute("INSERT INTO domains VALUES('2026-11-03', ?, 'wpad.box', 'other', 50, 0)", (MAC,))
        self.db.execute("INSERT INTO domains VALUES('2026-11-03', ?, 'moloco.com', 'other', 9, 0)", (MAC,))
        self.db.execute("INSERT INTO activity(mac, minute, cat) VALUES(?, 1, 'other'), (?, 2, 'social')", (MAC, MAC))
        wh.state_set(self.db, "schema", 1)
        wh.migrate(self.db)
        doms = dict(self.db.execute("SELECT domain, cat FROM domains").fetchall())
        self.assertEqual(doms, {"moloco.com": "ads"})
        self.assertEqual([r[0] for r in self.db.execute("SELECT cat FROM activity")], ["social"])
        self.assertEqual(wh.app_of("rr4---sn.googlevideo.com"), "YouTube")
        self.assertEqual(wh.app_of("teams.microsoft.com"), "Teams")
        self.assertTrue(wh.is_local_name("wpad.box"))


if __name__ == "__main__":
    unittest.main()

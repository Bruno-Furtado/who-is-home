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


if __name__ == "__main__":
    unittest.main()

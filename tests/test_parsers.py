# -*- coding: utf-8 -*-
"""
Leitores puros: tabela ARP, ifconfig, datas do AdGuard, registro de consultas, domínios, mDNS e NetBIOS.

    python3 -m unittest discover -s tests
"""
import os
import struct
import sys
import tempfile
import unittest

os.environ.setdefault("WHOISHOME_DATA", tempfile.mkdtemp(prefix="who-is-home-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import who_is_home as wh  # noqa: E402

# saída real de 'arp -anl' no macOS 11 (Big Sur)
ARP_MACOS = """Neighbor                Linklayer Address Expire(O) Expire(I)    Netif Refs Prbs
169.254.157.178         ac:aa:bb:cc:dd:dd 38s       2m32s          en4    2
192.168.0.1             6:2:aa:bb:c:1e    1m33s     1m33s          en4    1
192.168.0.23            da:aa:bb:cc:1:fd  1m50s     1m50s          en4    1
192.168.0.43            (incomplete)      expired   expired        en4    1
192.168.0.95            3c:aa:bb:cc:dd:7c 50s       50s            en4    1
192.168.0.255           ff:ff:ff:ff:ff:ff permanent permanent      en4    1
224.0.0.251             1:0:5e:0:0:fb     permanent permanent      en4    1
"""
IP_NEIGH = """192.168.0.1 dev eth0 lladdr 06:02:aa:bb:0c:1e REACHABLE
192.168.0.23 dev eth0 lladdr da:aa:bb:cc:01:fd STALE
192.168.0.50 dev eth0  FAILED
"""
IFCONFIG = """en4: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	options=404<VLAN_MTU,CHANNEL_IO>
	ether 38:aa:bb:cc:dd:eb
	inet6 fe80::1234:5678:9abc:def0%en4 prefixlen 64 secured scopeid 0xe
	inet 192.168.0.10 netmask 0xffffff00 broadcast 192.168.0.255
	status: active
"""


class ArpTest(unittest.TestCase):
    def test_macos(self):
        rows = wh.parse_arp_macos(ARP_MACOS)
        self.assertEqual([r["ip"] for r in rows], ["192.168.0.1", "192.168.0.23", "192.168.0.95"])
        self.assertEqual(rows[0]["mac"], "06:02:aa:bb:0c:1e")
        self.assertEqual(rows[0]["expire"], 93)
        self.assertEqual(rows[0]["iface"], "en4")

    def test_linux(self):
        rows = wh.parse_ip_neigh(IP_NEIGH)
        self.assertEqual([r["ip"] for r in rows], ["192.168.0.1", "192.168.0.23"])
        self.assertEqual(wh.alive_arp(rows), {"192.168.0.1"})

    def test_expire(self):
        self.assertEqual(wh.parse_expire("2m32s"), 152)
        self.assertEqual(wh.parse_expire("1h2m"), 3720)
        self.assertEqual(wh.parse_expire("expired"), 0)
        self.assertIsNone(wh.parse_expire("permanent"))

    def test_mac(self):
        self.assertEqual(wh.norm_mac("6:2:aa:bb:c:1e"), "06:02:aa:bb:0c:1e")
        self.assertIsNone(wh.norm_mac("(incomplete)"))
        self.assertTrue(wh.is_private_mac("da:aa:bb:cc:01:fd"))
        self.assertFalse(wh.is_private_mac("3c:aa:bb:cc:dd:7c"))


class InterfaceTest(unittest.TestCase):
    def test_ifconfig(self):
        self.assertEqual(wh.parse_ifconfig_inet(IFCONFIG, "192.168.0.10"), 24)
        self.assertEqual(wh.parse_ifconfig_ether(IFCONFIG), "38:aa:bb:cc:dd:eb")
        self.assertEqual(wh.parse_ifconfig_inet("    inet 10.0.0.5/22 brd 10.0.3.255 scope global eth0", "10.0.0.5"), 22)

    def test_targets(self):
        hosts = wh.scan_targets("192.168.0.10", 24)
        self.assertEqual(len(hosts), 253)
        self.assertNotIn("192.168.0.10", hosts)
        self.assertEqual(len(wh.scan_targets("10.0.0.5", 8)), 1021)     # limitado a /22


class AdGuardTest(unittest.TestCase):
    def test_time(self):
        self.assertAlmostEqual(wh.parse_rfc3339("2026-11-02T21:29:14.5-03:00"), wh.parse_rfc3339("2026-11-03T00:29:14.5Z"))
        self.assertAlmostEqual(wh.parse_rfc3339("2026-11-02T21:29:14.123456789-03:00") % 1, 0.123456789, places=5)
        self.assertIsNone(wh.parse_rfc3339("ontem"))

    def test_entry(self):
        e = {"client": "192.168.0.23", "question": {"name": "www.youtube.com", "type": "A", "class": "IN"},
             "reason": "NotFilteredNotFound", "time": "2026-11-02T21:29:14.1-03:00"}
        p = wh.parse_querylog_entry(e)
        self.assertEqual((p["ip"], p["name"], p["blocked"]), ("192.168.0.23", "www.youtube.com", False))
        self.assertTrue(wh.parse_querylog_entry(dict(e, reason="FilteredBlackList"))["blocked"])
        self.assertFalse(wh.parse_querylog_entry(dict(e, reason="FilteredSafeSearch"))["blocked"])
        self.assertIsNone(wh.parse_querylog_entry(dict(e, question={"name": "servidor.local", "type": "A"})))
        self.assertIsNone(wh.parse_querylog_entry(dict(e, question={"name": "10.0.168.192.in-addr.arpa", "type": "PTR"})))
        self.assertIsNone(wh.parse_querylog_entry("lixo"))


class DomainTest(unittest.TestCase):
    def test_base(self):
        self.assertEqual(wh.base_domain("www.g1.globo.com"), "globo.com")
        self.assertEqual(wh.base_domain("a.b.mercadolivre.com.br"), "mercadolivre.com.br")
        self.assertEqual(wh.base_domain("localhost"), "localhost")

    def test_category(self):
        self.assertEqual(wh.categorize("rr3---sn-x.googlevideo.com"), "video")
        self.assertEqual(wh.categorize("g1.globo.com"), "news")          # mais específico ganha
        self.assertEqual(wh.categorize("globoplay.globo.com"), "video")
        self.assertEqual(wh.categorize("exemplo-qualquer.com.br"), "other")
        self.assertEqual(wh.display_domain("music.youtube.com"), "music.youtube.com")
        self.assertEqual(wh.display_domain("i.ytimg.com"), "ytimg.com")

    def test_local(self):
        for n in ("servidor.local", "wpad", "printer", "x.in-addr.arpa", ""):
            self.assertTrue(wh.is_local_name(n), n)
        self.assertFalse(wh.is_local_name("google.com"))

    def test_kind(self):
        self.assertEqual(wh.guess_kind("Anas-iPhone-Pro"), "phone")
        self.assertEqual(wh.guess_kind("HPAABBCCDDF3"), "printer")
        self.assertEqual(wh.guess_kind("LGwebOSTV"), "tv")
        self.assertIsNone(wh.guess_kind("servidor"))


class NameProtocolTest(unittest.TestCase):
    def test_mdns_roundtrip(self):
        q = wh.mdns_ptr_query("192.168.0.219", qid=7)
        # resposta: cabeçalho + pergunta repetida + PTR com ponteiro para a pergunta
        name = b"\x0fAnas-iPhone-Pro\x05local\x00"
        ans = b"\xc0\x0c" + struct.pack(">HHIH", 12, 1, 10, len(name)) + name
        resp = struct.pack(">HHHHHH", 7, 0x8400, 1, 1, 0, 0) + q[12:] + ans
        self.assertEqual(wh.parse_ptr_answer(resp), "Anas-iPhone-Pro")
        self.assertIsNone(wh.parse_ptr_answer(b"\x00" * 5))

    def test_netbios(self):
        q = wh.netbios_query()
        self.assertEqual(len(q), 12 + 34 + 4)
        names = b"DESKTOP-8KQ2   \x00\x04\x00" + b"WORKGROUP      \x00\x84\x00"
        resp = struct.pack(">HHHHHH", 0x5749, 0x8400, 0, 1, 0, 0) + q[12:12 + 34] + struct.pack(">HHIH", 0x21, 1, 0, 1 + len(names)) + b"\x02" + names
        self.assertEqual(wh.parse_netbios_answer(resp), "DESKTOP-8KQ2")

    def test_clean(self):
        self.assertEqual(wh.clean_hostname("Sala.local."), "Sala")
        self.assertIsNone(wh.clean_hostname(".local"))


class WebTest(unittest.TestCase):
    def test_host(self):
        self.assertTrue(wh.host_allowed("192.168.0.10:8080", []))
        self.assertTrue(wh.host_allowed("servidor.local:8080", []))
        self.assertTrue(wh.host_allowed("[::1]:8080", []))
        self.assertFalse(wh.host_allowed("evil.com", []))
        self.assertTrue(wh.host_allowed("casa.example", ["casa.example"]))

    def test_device_update(self):
        u = wh.parse_device_update(b'{"mac": "6:2:aa:bb:c:1e", "nickname": "  TV\\n da sala ", "kind": "tv"}')
        self.assertEqual(u, {"mac": "06:02:aa:bb:0c:1e", "nickname": "TV da sala", "kind": "tv"})
        self.assertIsNone(wh.parse_device_update(b'{"mac": "06:02:aa:bb:0c:1e", "nickname": ""}')["nickname"])
        with self.assertRaises(ValueError):
            wh.parse_device_update(b'{"mac": "../etc", "nickname": "x"}')
        with self.assertRaises(ValueError):
            wh.parse_device_update(b'{"mac": "06:02:aa:bb:0c:1e", "kind": "<script>"}')


if __name__ == "__main__":
    unittest.main()

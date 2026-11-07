# -*- coding: utf-8 -*-
"""
Confere as traduções: todos os idiomas com as mesmas chaves e os mesmos {marcadores},
e toda chave usada no HTML/JS existindo no dicionário.

    python3 -m unittest discover -s tests
"""
import json
import os
import re
import sys
import tempfile
import unittest

os.environ.setdefault("WHOISHOME_DATA", tempfile.mkdtemp(prefix="who-is-home-test-"))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import who_is_home as wh  # noqa: E402

STATIC = os.path.join(ROOT, "static")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# chaves montadas em tempo de execução ("cat." + código, "kind." + tipo...)
DYNAMIC_PREFIXES = ("cat.", "kind.", "src.", "ev.", "ntfy.err.", "title.")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


def ui_dict():
    src = read("i18n.js")
    body = src[src.index("const I18N = ") + len("const I18N = "):src.rindex("};") + 1]
    return json.loads(body)


class ParityMixin:
    def check_parity(self, table):
        base = table["en"]
        for lang, texts in table.items():
            self.assertEqual(set(texts), set(base), "chaves diferentes em %s: %s" % (lang, set(texts) ^ set(base)))
            for key, value in texts.items():
                self.assertEqual(set(PLACEHOLDER.findall(value)), set(PLACEHOLDER.findall(base[key])),
                                 "marcadores diferentes em %s.%s" % (lang, key))


class UiTest(ParityMixin, unittest.TestCase):
    def test_parity(self):
        self.check_parity(ui_dict())

    def test_used_keys_exist(self):
        keys = set(ui_dict()["en"])
        used = set()
        for name in ("index.html", "device.html", "wrapped.html", "person.html"):
            used |= set(re.findall(r'data-i18n(?:-html|-title)?="([^"]+)"', read(name)))
        for name in ("app.js", "device.js", "common.js", "wrapped.js", "person.js"):
            used |= set(re.findall(r'\bt\("([^"]+)"', read(name)))
        missing = {k for k in used if k not in keys and not k.endswith(".")}
        self.assertEqual(missing, set())

    def test_dynamic_keys(self):
        keys = set(ui_dict()["en"])
        for cat in wh.CATEGORIES:
            self.assertIn("cat." + cat, keys)
        self.assertIn("cat.other", keys)
        for kind in wh.KINDS:
            self.assertIn("kind." + kind, keys)


class ServerTest(ParityMixin, unittest.TestCase):
    def test_parity(self):
        self.check_parity(wh.TEXTS)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""
Arquivos estáticos: todo arquivo da lista existe, e o HTML e o manifesto só apontam para arquivos servidos.

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


class StaticTest(unittest.TestCase):
    def test_files_exist(self):
        for path, (name, _) in wh.STATIC_FILES.items():
            self.assertTrue(os.path.isfile(os.path.join(wh.STATIC, name)), "%s → %s" % (path, name))

    def test_html_refs_are_served(self):
        for name in ("index.html", "device.html", "wrapped.html"):
            with open(os.path.join(wh.STATIC, name), encoding="utf-8") as f:
                html = f.read()
            for ref in re.findall(r'(?:src|href)="(/[^"]*)"', html):
                self.assertIn(ref, wh.STATIC_FILES, "%s aponta para %s" % (name, ref))
            self.assertNotIn("<script>", html, "%s: script inline viola a CSP" % name)
            self.assertNotRegex(html, r"\son[a-z]+=", "%s: evento inline viola a CSP" % name)

    def test_manifest(self):
        with open(os.path.join(wh.STATIC, "manifest.webmanifest"), encoding="utf-8") as f:
            manifest = json.load(f)
        for icon in manifest["icons"]:
            self.assertIn(icon["src"], wh.STATIC_FILES)


if __name__ == "__main__":
    unittest.main()

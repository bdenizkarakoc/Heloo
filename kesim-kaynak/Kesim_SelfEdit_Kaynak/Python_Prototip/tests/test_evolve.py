import os
import unittest

from selfedit import config, paths, telemetry
from selfedit.evolve import engine, store, validator

from .helpers import TempHome

GOOD = '''NAME = "invertx"
DESCRIPTION = "deneme"
PARAMS = {"amount": 1.0}


def video_filter(params, ctx):
    return "negate"
'''


@unittest.skipIf(os.environ.get("SELFEDIT_IN_SANDBOX"), "sandbox içinde tekrar çalıştırılmaz")
class EvolveTests(unittest.TestCase):
    def setUp(self):
        self.home = TempHome()

    def tearDown(self):
        self.home.close()

    # --- statik tarama ---
    def test_static_accepts_good(self):
        self.assertEqual(validator.static_check(GOOD, "invertx"), [])

    def test_static_rejects_dangerous_code(self):
        bad = {
            "import os": GOOD.replace('NAME', "import os\nNAME", 1),
            "import subprocess": GOOD.replace('NAME', "import subprocess\nNAME", 1),
            "open": GOOD.replace('return "negate"', 'return open("/etc/passwd").read()'),
            "eval": GOOD.replace('return "negate"', 'return eval("1")'),
            "dunder": GOOD.replace('return "negate"', 'return ().__class__.__name__'),
            "top-level call": GOOD + '\nprint("hi")\n',
            "top-level exec on import": GOOD.replace('PARAMS = {"amount": 1.0}', 'PARAMS = dict(amount=1.0)'),
            "class": GOOD + "\n\nclass X:\n    pass\n",
            "lambda": GOOD.replace('return "negate"', 'return (lambda: "negate")()'),
        }
        for label, code in bad.items():
            with self.subTest(label):
                self.assertTrue(validator.static_check(code, "invertx"), label)

    def test_static_rejects_wrong_name_and_size(self):
        self.assertTrue(validator.static_check(GOOD, "Bad-Name"))
        self.assertTrue(validator.static_check(GOOD, "other"))  # NAME ile uyuşmuyor
        self.assertTrue(validator.static_check(GOOD + "# " + "x" * 9000, "invertx"))

    # --- sandbox ---
    def test_validate_good_plugin(self):
        rep = validator.validate(GOOD, "invertx", run_suite=False)
        self.assertTrue(rep["ok"], rep)

    def test_validate_catches_filter_that_breaks_render(self):
        bad = GOOD.replace('return "negate"', 'return "nonexistent_filter=1"')
        rep = validator.validate(bad, "invertx", run_suite=False)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["steps"][-1]["step"], "sandbox render")

    def test_size_changing_filter_is_neutralized_by_renderer(self):
        # Render her klibin sonunda boyutu sabitler; çıktı boyutu bozulamaz.
        odd = GOOD.replace('return "negate"', 'return "scale=100:100"')
        rep = validator.validate(odd, "invertx", run_suite=False)
        self.assertTrue(rep["ok"], rep)

    # --- tam döngü ---
    def test_offline_cycle_approve_mode_then_apply_and_rollback(self):
        config.set_value("mode", "approve")
        res = engine.run_cycle(offline=True, run_suite=False, force=True)
        self.assertEqual(res["result"], "validated", res)
        target = paths.plugins() / f"{res['plugin']}.py"
        self.assertFalse(target.exists(), "onay modunda kendiliğinden uygulanmamalı")

        out = engine.apply(res["id"])
        self.assertTrue(out["ok"], out)
        self.assertTrue(target.exists())
        self.assertEqual(store.load(res["id"])["status"], "applied")

        out = engine.rollback(res["id"])
        self.assertTrue(out["ok"])
        self.assertFalse(target.exists())

    def test_auto_mode_applies_validated(self):
        config.set_value("mode", "auto")
        res = engine.run_cycle(offline=True, run_suite=False, force=True)
        self.assertEqual(res["result"], "applied", res)
        self.assertTrue((paths.plugins() / f"{res['plugin']}.py").exists())

    def test_wish_steers_proposal(self):
        telemetry.log("wish", text="Videoya piksel mozaik efekti istiyorum")
        res = engine.run_cycle(offline=True, run_suite=False, force=True)
        self.assertEqual(res["plugin"], "pixelate", res)

    def test_failed_proposal_is_never_applied(self):
        bad = GOOD.replace('return "negate"', 'return "nonexistent_filter=1"')
        prop = {"id": store.new_id("invertx"), "created": 0, "plugin_name": "invertx", "title": "x",
                "rationale": "", "code": bad, "source": "test", "status": "failed", "validation": None}
        store.save(prop)
        self.assertFalse(engine.apply(prop["id"])["ok"])
        self.assertFalse((paths.plugins() / "invertx.py").exists())

    def test_daily_limit(self):
        config.set_value("max_per_day", 1)
        engine.run_cycle(offline=True, run_suite=False, force=True)
        res = engine.run_cycle(offline=True, run_suite=False)
        self.assertEqual(res["result"], "skipped")

    def test_rejected_name_not_reproposed(self):
        res = engine.run_cycle(offline=True, run_suite=False, force=True)
        engine.reject(res["id"])
        res2 = engine.run_cycle(offline=True, run_suite=False, force=True)
        self.assertNotEqual(res2.get("plugin"), res["plugin"])


if __name__ == "__main__":
    unittest.main()

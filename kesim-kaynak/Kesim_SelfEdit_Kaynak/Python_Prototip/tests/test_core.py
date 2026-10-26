import tempfile
import unittest
from pathlib import Path

from selfedit import ffmpeg, project, render, telemetry
from selfedit.effects import EffectError, load_registry

from .helpers import TempHome


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.home = TempHome()
        self.d = Path(tempfile.mkdtemp())
        ffmpeg.make_test_video(self.d / "a.mp4", 2, True)
        ffmpeg.make_test_video(self.d / "b.mp4", 2, False)

    def tearDown(self):
        self.home.close()

    def _proj(self):
        return project.new_project(320, 240, 30)

    def test_builtin_effects_load(self):
        reg = load_registry()
        for n in ("grayscale", "brightness", "blur", "fade", "speed", "volume", "text"):
            self.assertIn(n, reg.names())
        self.assertEqual(reg.errors, {})

    def test_render_single_clip_with_effects(self):
        p = self._proj()
        project.add_clip(p, "a.mp4")
        for fx in ("grayscale", "blur", "brightness", "fade", "volume"):
            project.add_effect(p, 0, fx)
        render.render_project(p, self.d / "o.mp4", self.d)
        info = ffmpeg.probe(self.d / "o.mp4")
        self.assertTrue(info["has_video"] and info["has_audio"])
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.2)
        self.assertEqual((info["width"], info["height"]), (320, 240))

    def test_concat_mixed_audio_and_trim(self):
        p = self._proj()
        project.add_clip(p, "a.mp4", 0, 1)
        project.add_clip(p, "b.mp4")  # sesi olmayan klip
        render.render_project(p, self.d / "o.mp4", self.d)
        info = ffmpeg.probe(self.d / "o.mp4")
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.25)
        self.assertTrue(info["has_audio"])

    def test_speed_halves_duration(self):
        p = self._proj()
        project.add_clip(p, "a.mp4")
        project.add_effect(p, 0, "speed", {"factor": 2})
        render.render_project(p, self.d / "o.mp4", self.d)
        self.assertAlmostEqual(ffmpeg.probe(self.d / "o.mp4")["duration"], 1.0, delta=0.2)

    def test_text_overlay_with_special_characters(self):
        p = self._proj()
        project.add_clip(p, "a.mp4")
        project.add_effect(p, 0, "text", {"text": "Merhaba: dünya, [test] 'x'; 50%", "start": 0.2, "end": 1.0})
        render.render_project(p, self.d / "o.mp4", self.d)
        self.assertTrue((self.d / "o.mp4").exists())

    def test_bad_params_rejected(self):
        p = self._proj()
        project.add_clip(p, "a.mp4")
        project.add_effect(p, 0, "text", {"x": "1; rm -rf /"})
        with self.assertRaises(render.RenderError):
            render.render_project(p, self.d / "o.mp4", self.d)

    def test_unknown_effect_is_logged_for_evolution(self):
        p = self._proj()
        project.add_clip(p, "a.mp4")
        project.add_effect(p, 0, "sepia_xyz")
        with self.assertRaises(render.RenderError):
            render.render_project(p, self.d / "o.mp4", self.d)
        self.assertIn("sepia_xyz", telemetry.summarize()["unknown_effects_requested"])

    def test_broken_plugin_does_not_break_others(self):
        from selfedit import paths
        (paths.plugins() / "broken.py").write_text("this is not python(", encoding="utf-8")
        reg = load_registry()
        self.assertIn("grayscale", reg.names())
        self.assertIn("broken.py", reg.errors)


if __name__ == "__main__":
    unittest.main()

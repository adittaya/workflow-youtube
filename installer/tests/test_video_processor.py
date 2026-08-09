"""Tests for video_processor trim clamping — shorts must not collapse to 1s."""

import unittest
from unittest import mock

import video_processor


def fake_info(duration):
    return {
        "streams": [{
            "codec_type": "video",
            "duration": str(duration),
            "width": 720,
            "height": 1280,
        }],
        "format": {"duration": str(duration)},
    }


class TrimClampTests(unittest.TestCase):

    def _run(self, duration, trim_start, trim_end, fps=24):
        captured = {}

        def fake_run(cmd, desc):
            captured["cmd"] = cmd
            return mock.Mock(stdout="{}", returncode=0)

        with mock.patch.object(video_processor, "get_video_info",
                               return_value=fake_info(duration)), \
                mock.patch.object(video_processor, "_run", side_effect=fake_run):
            video_processor.apply_edits("in.mp4", "out.mp4", {
                "trim_start": trim_start,
                "trim_end": trim_end,
                "fps": fps,
            })
        cmd = captured["cmd"]
        ss = float(cmd[cmd.index("-ss") + 1]) if "-ss" in cmd else 0.0
        t = float(cmd[cmd.index("-t") + 1]) if "-t" in cmd else float(duration)
        return ss, t

    def test_shorts_never_collapse_to_one_second(self):
        # Regression: 30s Short with 15s+15s trims used to upload exactly 1s.
        for duration in (30, 25, 20):
            for ts, te in ((15, 15), (12, 10)):
                ss, t = self._run(duration, ts, te)
                self.assertGreaterEqual(t, 3.0,
                    f"src={duration}s trims={ts}/{te} collapsed to {t}s")

    def test_long_video_trims_untouched(self):
        ss, t = self._run(600, 15, 15)
        self.assertEqual((ss, t), (15.0, 570.0))

    def test_exact_40_percent_boundary_keeps_twenty_seconds(self):
        ss, t = self._run(50, 20, 15)
        self.assertEqual(t, 20.0)

    def test_tiny_clip_trims_to_near_nothing(self):
        ss, t = self._run(3, 15, 15)
        self.assertEqual(t, 3.0)

    def test_get_duration_prefers_video_stream(self):
        info = {
            "streams": [{"codec_type": "video", "duration": "120.5"}],
            "format": {"duration": "999"},
        }
        self.assertEqual(video_processor.get_duration(info), 120.5)

    def test_get_duration_falls_back_to_format(self):
        info = {"streams": [], "format": {"duration": "42.0"}}
        self.assertEqual(video_processor.get_duration(info), 42.0)

    def test_get_duration_missing_returns_zero(self):
        self.assertEqual(video_processor.get_duration({}), 0.0)


if __name__ == "__main__":
    unittest.main()

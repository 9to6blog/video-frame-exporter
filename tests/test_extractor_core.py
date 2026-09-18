from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from extractor_core import export_frames, probe_video


class ExtractorCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / "sample.avi"
        writer = cv2.VideoWriter(
            str(self.video),
            cv2.VideoWriter_fourcc(*"MJPG"),
            10.0,
            (64, 48),
        )
        self.assertTrue(writer.isOpened())
        for index in range(8):
            frame = np.full((48, 64, 3), index * 25, dtype=np.uint8)
            writer.write(frame)
        writer.release()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_probe_video(self) -> None:
        info = probe_video(self.video)
        self.assertEqual(info.frame_count, 8)
        self.assertEqual((info.width, info.height), (64, 48))
        self.assertAlmostEqual(info.fps, 10.0, places=1)

    def test_export_inclusive_range(self) -> None:
        output = self.root / "frames"
        result = export_frames(self.video, output, 2, 5, "png")
        self.assertEqual(result.exported, 4)
        self.assertEqual(result.last_frame, 5)
        self.assertEqual(
            [p.name for p in sorted(output.glob("*.png"))],
            [
                "frame_000002.png",
                "frame_000003.png",
                "frame_000004.png",
                "frame_000005.png",
            ],
        )

    def test_export_all_until_end_of_stream(self) -> None:
        output = self.root / "all_frames"
        result = export_frames(self.video, output, 0, None, "jpg")
        self.assertEqual(result.exported, 8)
        self.assertEqual(result.last_frame, 7)
        self.assertEqual(len(list(output.glob("*.jpg"))), 8)

    def test_invalid_range(self) -> None:
        with self.assertRaises(ValueError):
            export_frames(self.video, self.root / "bad", 5, 2)


if __name__ == "__main__":
    unittest.main()

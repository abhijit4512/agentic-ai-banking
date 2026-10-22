"""Basic integration test for the local Tesseract executable."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tesseract_ocr import extract_text


class TesseractOcrTest(unittest.TestCase):
    def test_extracts_known_text(self) -> None:
        configured_command = os.getenv("TESSERACT_CMD")
        executable = (
            Path(configured_command)
            if configured_command
            else Path(shutil.which("tesseract") or "")
        )
        if not executable.is_file():
            self.skipTest("Install Tesseract and put it on PATH or set TESSERACT_CMD.")

        image = Image.new("RGB", (720, 140), "white")
        draw = ImageDraw.Draw(image)
        draw.text(
            (24, 28),
            "FINPILOT OCR TEST 12345",
            fill="black",
            font=ImageFont.load_default(size=48),
        )
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "known-text.png"
            image.save(image_path)
            text = extract_text(image_path, psm=6)

        self.assertIn("FINPILOT", text.upper())
        self.assertIn("12345", text)


if __name__ == "__main__":
    unittest.main()

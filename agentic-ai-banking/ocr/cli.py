"""Command-line interface for local Tesseract OCR."""

from __future__ import annotations

import argparse
import json
import sys

from tesseract_ocr import extract_text, extract_text_with_confidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from an image with Tesseract.")
    parser.add_argument("image", help="Path to a supported image file")
    parser.add_argument("--lang", default="eng", help="Tesseract language code (default: eng)")
    parser.add_argument("--psm", type=int, default=3, help="Tesseract page segmentation mode")
    parser.add_argument(
        "--confidence",
        action="store_true",
        help="Include per-word confidence scores in JSON output",
    )
    parser.add_argument("--no-grayscale", action="store_true", help="Skip grayscale conversion")
    parser.add_argument("--no-upscale", action="store_true", help="Skip small-image upscaling")
    parser.add_argument("--threshold", action="store_true", help="Apply binary thresholding")
    args = parser.parse_args()

    options = {
        "grayscale": not args.no_grayscale,
        "upscale": not args.no_upscale,
        "threshold": args.threshold,
    }
    try:
        if args.confidence:
            text, words = extract_text_with_confidence(
                args.image,
                lang=args.lang,
                psm=args.psm,
                **options,
            )
            print(json.dumps({"text": text, "words": words}, ensure_ascii=False, indent=2))
        else:
            print(extract_text(args.image, lang=args.lang, psm=args.psm, **options))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

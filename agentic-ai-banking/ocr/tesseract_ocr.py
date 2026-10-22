"""Local image-to-text OCR using the Tesseract engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output
from pytesseract.pytesseract import TesseractNotFoundError


class WordConfidence(TypedDict):
    word: str
    confidence: float


def _open_image(image_path: str | os.PathLike[str]) -> Image.Image:
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    try:
        with Image.open(path) as image:
            image.load()
            return image.copy()
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported image format: {path}") from exc


def _prepare_image(
    image: Image.Image,
    *,
    grayscale: bool,
    upscale: bool,
    threshold: bool,
) -> Image.Image:
    prepared = ImageOps.exif_transpose(image)
    if grayscale:
        prepared = ImageOps.grayscale(prepared)
    if upscale and max(prepared.size) < 1000:
        prepared = prepared.resize(
            (prepared.width * 2, prepared.height * 2),
            Image.Resampling.LANCZOS,
        )
    if threshold:
        prepared = ImageOps.grayscale(prepared).point(
            lambda pixel: 255 if pixel >= 160 else 0
        )
    return prepared


def _configure_tesseract() -> None:
    command = os.getenv("TESSERACT_CMD")
    pytesseract.pytesseract.tesseract_cmd = command or "tesseract"


def _raise_clear_tesseract_error(exc: TesseractNotFoundError) -> None:
    command = os.getenv("TESSERACT_CMD")
    if command:
        message = (
            f"Tesseract is not installed or could not be found at TESSERACT_CMD "
            f"({command!r}). Install the Tesseract engine and check that path."
        )
    else:
        message = (
            "Tesseract is not installed or is not on PATH. Install the Tesseract "
            "engine, or set TESSERACT_CMD to its executable path."
        )
    raise RuntimeError(message) from exc


def extract_text(
    image_path: str | os.PathLike[str],
    lang: str = "eng",
    psm: int = 3,
    *,
    grayscale: bool = True,
    upscale: bool = True,
    threshold: bool = False,
) -> str:
    """Extract text from an image, optionally preprocessing it before OCR."""
    image = _prepare_image(
        _open_image(image_path),
        grayscale=grayscale,
        upscale=upscale,
        threshold=threshold,
    )
    _configure_tesseract()
    try:
        return pytesseract.image_to_string(
            image,
            lang=lang,
            config=f"--psm {psm}",
        ).strip()
    except TesseractNotFoundError as exc:
        _raise_clear_tesseract_error(exc)


def extract_text_with_confidence(
    image_path: str | os.PathLike[str],
    lang: str = "eng",
    psm: int = 3,
    *,
    grayscale: bool = True,
    upscale: bool = True,
    threshold: bool = False,
) -> tuple[str, list[WordConfidence]]:
    """Return recognized text and confidence scores for each recognized word."""
    image = _prepare_image(
        _open_image(image_path),
        grayscale=grayscale,
        upscale=upscale,
        threshold=threshold,
    )
    _configure_tesseract()
    try:
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config=f"--psm {psm}",
            output_type=Output.DICT,
        )
    except TesseractNotFoundError as exc:
        _raise_clear_tesseract_error(exc)

    words: list[WordConfidence] = []
    for word, raw_confidence in zip(data["text"], data["conf"]):
        word = word.strip()
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue
        if word and confidence >= 0:
            words.append({"word": word, "confidence": confidence})
    return " ".join(item["word"] for item in words), words

# Optional manual integration

This OCR utility runs locally and is not connected to the application. Install the
Tesseract engine and the Python dependencies first. For code running from the project
root, add the following where a local image needs OCR:

```python
from ocr.tesseract_ocr import extract_text

text = extract_text(image_path, lang="eng", psm=3)
```

To try it from the existing KYC backend, an integration could be added manually in
`backend/app/kyc.py`, where the current image-to-text extraction is implemented. Convert
the image bytes to a temporary local image file (or adapt this utility to accept bytes)
before calling `extract_text`; do not send identity documents to a remote OCR provider.
Consider temporary-file cleanup, encrypted storage, error handling, and reviewer workflow
before integrating. This project's existing code has not been modified.

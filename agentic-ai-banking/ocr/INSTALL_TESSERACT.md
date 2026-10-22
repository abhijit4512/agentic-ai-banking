# Install the Tesseract OCR engine

`pytesseract` is a Python wrapper. The separate Tesseract executable must also be installed.

## Windows

1. Install a Windows build from the [UB Mannheim Tesseract project](https://github.com/UB-Mannheim/tesseract/wiki).
2. In PowerShell, set the executable path for the current terminal:

   ```powershell
   $env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```

3. Check the installation and available languages:

   ```powershell
   & $env:TESSERACT_CMD --version
   & $env:TESSERACT_CMD --list-langs
   ```

## macOS

```sh
brew install tesseract
tesseract --version
tesseract --list-langs
```

## Ubuntu / Debian

```sh
sudo apt update
sudo apt install tesseract-ocr
tesseract --version
tesseract --list-langs
```

## Additional languages

OCR languages are selected by their Tesseract language code, such as `eng` or `fra`.
Install the matching language data for the engine:

- On Ubuntu/Debian, install a package such as `tesseract-ocr-fra`.
- On macOS, install or copy the corresponding trained data into Tesseract's `tessdata`
  directory; check your package manager's available language-data packages.
- On Windows, use the installer's language options or add the matching `.traineddata`
  file to the installation's `tessdata` directory.

Run `tesseract --list-langs` (or the configured executable with `--list-langs`) to
confirm that a language is available. Then pass its code, for example
`extract_text("document.png", lang="eng+fra")`.

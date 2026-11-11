import io
from typing import Annotated

import pytesseract
from fastapi import FastAPI, File, UploadFile
from PIL import Image

main = FastAPI(title="OCR Service")


@main.get("/health")
def health_check():
    return {"status": "healthy"}


@main.post("/ocr")
async def extract_text(file: Annotated[UploadFile, File()]):
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    # Extraction multilingue arabe + français
    text = pytesseract.image_to_string(image, lang="ara+fra")
    return {"text": text}

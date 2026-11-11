
import io
from typing import Annotated

import pytesseract
from fastapi import FastAPI, File, Form, UploadFile
from PIL import Image

main = FastAPI(title="OCR Service")


@main.get("/health")
def health_check():
    return {"status": "healthy"}


@main.post("/ocr")
async def extract_text(
    image: Annotated[UploadFile, File()],
    lang: Annotated[str, Form()] = "ara",
):
    image_bytes = await image.read()
    pil_image = Image.open(io.BytesIO(image_bytes))

    text = pytesseract.image_to_string(pil_image, lang=lang)

    data = pytesseract.image_to_data(
        pil_image,
        lang=lang,
        output_type=pytesseract.Output.DICT,
    )

    confidences = [
        float(conf)
        for conf in data["conf"]
        if float(conf) != -1
    ]

    confidence = (
       max(0.0, min(1.0, sum(confidences) / len(confidences) / 100))
      if confidences
      else 0.0
    )

    return {
        "text": text,
        "confidence": confidence,
    }

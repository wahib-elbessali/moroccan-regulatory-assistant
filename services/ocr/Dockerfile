FROM python:3.11-slim

# Install Tesseract OCR and Arabic + French language packs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-fra \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install lightweight web server / API dependencies for the OCR wrapper
RUN pip install --no-cache-dir fastapi uvicorn pytesseract pillow

# Copy the lightweight server code
COPY app.py /app/app.py

EXPOSE 8070
CMD ["uvicorn", "app:main", "--host", "0.0.0.0", "--port", "8070"]



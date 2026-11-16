FROM python:3.11-slim

WORKDIR /app

# CPU build of torch: no CUDA libraries, so the image stays a few hundred MB instead of several GB.
# On a GPU demo machine, install the default torch wheel instead.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir fastapi uvicorn pyyaml "sentence-transformers>=3.0"

# Models come from the hf_cache volume, mounted on /hf; nothing is ever downloaded at startup.
ENV HF_HOME=/hf HF_HUB_OFFLINE=1

COPY app.py /app/app.py

EXPOSE 8080
CMD ["uvicorn", "app:main", "--host", "0.0.0.0", "--port", "8080"]
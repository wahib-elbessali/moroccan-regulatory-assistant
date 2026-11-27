.PHONY: models up up-light up-gpu up-cloud up-light-gpu down test-isolation seed

# Owner of the `upload` rows of data/raw/manifest.csv. document_rights is fake for now, so this
# development UUID is not checked against a user. Override: `make seed OWNER=<uuid>`.
OWNER ?= 00000000-0000-0000-0000-000000000001

models:
	python services/download_models.py

up:
	docker compose up -d --wait

up-light:
	MODE=light docker compose up -d --wait

# Same as `up`, with the NVIDIA card given to Ollama and to the models service (see docker-compose.gpu.yml).
up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait

down:
	docker compose down

test-isolation:
	pytest tests/sovereignty/test_network_isolation.py -v

# Registers the corpus of data/raw in web-search, then marks the public documents non-blocking
# (what P5's set_document_roles will do by itself once its routes exist).
seed:
	docker compose exec api python -m src.ingestion.cli seed --owner $(OWNER) --raw-dir /app/data/raw
	docker compose exec -T api python - < scripts/leak_unblock_public.py

# Cloud mode: Gemini through the isolated cloud-gateway.
up-cloud:
	MODE=cloud ALLOW_CLOUD_LLM=true docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile cloud up -d --wait

# Return to the local light model with GPU support.
up-light-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile cloud rm -sf cloud-gateway
	MODE=light ALLOW_CLOUD_LLM=false docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait

.PHONY: models up up-light up-gpu warm down test-isolation seed

# Owner of the `upload` rows of data/raw/manifest.csv. document_rights is fake for now, so this
# development UUID is not checked against a user. Override: `make seed OWNER=<uuid>`.
OWNER ?= 00000000-0000-0000-0000-000000000001

models:
	python services/download_models.py

up:
	docker compose up -d --wait
	$(MAKE) warm

up-light:
	MODE=light docker compose up -d --wait
	$(MAKE) warm

# Same as `up`, with the NVIDIA card given to Ollama and to the models service (see docker-compose.gpu.yml).
up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait
	$(MAKE) warm

# Loads the answer model and the narration model onto the card, so the first question does not
# time out while they load. The `up` targets run it; run it by hand after a plain `docker compose up`.
warm:
	docker compose exec -T api python -m src.core.llm.warmup

down:
	docker compose down

test-isolation:
	pytest tests/sovereignty/test_network_isolation.py -v

# Registers the corpus of data/raw in web-search, then marks the public documents non-blocking
# (what P5's set_document_roles will do by itself once its routes exist).
seed:
	docker compose exec api python -m src.ingestion.cli seed --owner $(OWNER) --raw-dir /app/data/raw
	docker compose exec -T api python - < scripts/leak_unblock_public.py
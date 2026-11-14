.PHONY: models up up-light down test-isolation seed

models:
	python services/download_models.py

up:
	docker compose up -d --wait

up-light:
	MODE=light docker compose up -d --wait

down:
	docker compose down

test-isolation:
	pytest tests/sovereignty/test_network_isolation.py -v

seed:
	docker compose exec api python -m src.ingestion seed.PHONY: models up up-light down test-isolation seed

# Owner of the `upload` rows of data/raw/manifest.csv. document_rights is fake for now, so this
# development UUID is not checked against a user. Override: `make seed OWNER=<uuid>`.
OWNER ?= 00000000-0000-0000-0000-000000000001

models:
	python services/download_models.py

up:
	docker compose up -d --wait

up-light:
	MODE=light docker compose up -d --wait

down:
	docker compose down

test-isolation:
	pytest tests/sovereignty/test_network_isolation.py -v

# Registers the corpus of data/raw in web-search, then marks the public documents non-blocking
# (what P5's set_document_roles will do by itself once its routes exist).
seed:
	docker compose exec api python -m src.ingestion.cli seed --owner $(OWNER) --raw-dir /app/data/raw
	docker compose exec -T api python - < scripts/leak_unblock_public.py
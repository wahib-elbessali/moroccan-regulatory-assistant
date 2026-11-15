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
	docker compose exec api python -m src.ingestion seed
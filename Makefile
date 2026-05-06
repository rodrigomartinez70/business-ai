# ─────────────────────────────────────────────────────────────
# Comandos de desarrollo y testing
# ─────────────────────────────────────────────────────────────

TEST_DB_URL     := postgresql://test_admin:test_password@localhost:5435/test_negocio_db
TEST_API_GERENTE := test-key-gerente
TEST_API_ADMIN  := test-key-admin
TEST_API_RECEP  := test-key-recepcion

.PHONY: help test test-up test-down test-logs install-test

help:
	@echo "Comandos disponibles:"
	@echo "  make test          — Levanta DB de test, corre pytest, baja DB"
	@echo "  make test-up       — Levanta solo la DB de test"
	@echo "  make test-down     — Baja la DB de test"
	@echo "  make test-logs     — Ver logs de la DB de test"
	@echo "  make install-test  — Instala dependencias de test"

install-test:
	pip install -r requirements-test.txt
	pip install -r api/requirements.txt

test-up:
	docker compose -f docker-compose.test.yml up -d
	@echo "Esperando que postgres de test esté listo..."
	@until docker compose -f docker-compose.test.yml exec -T postgres_test pg_isready -U test_admin -d test_negocio_db 2>/dev/null; do \
		printf "."; sleep 1; \
	done
	@echo " listo."

test-down:
	docker compose -f docker-compose.test.yml down -v

test-logs:
	docker compose -f docker-compose.test.yml logs postgres_test

test: test-up
	DATABASE_URL="$(TEST_DB_URL)" \
	INGEST_DATABASE_URL="$(TEST_DB_URL)" \
	BUSINESS_CONFIG_PATH="api/config.yaml" \
	API_KEY_GERENTE="$(TEST_API_GERENTE)" \
	API_KEY_ADMINISTRACION="$(TEST_API_ADMIN)" \
	API_KEY_RECEPCION="$(TEST_API_RECEP)" \
	ANTHROPIC_API_KEY="" \
	OLLAMA_URL="http://localhost:11434" \
	PYTHONPATH="api" \
	python3 -m pytest tests/ -v --tb=short -p no:anyio 2>&1; \
	EXIT_CODE=$$?; \
	$(MAKE) test-down; \
	exit $$EXIT_CODE

IMAGE ?= grocy-recipe-import:latest
CONTAINER ?= grocy-recipe-import
ENV_FILE ?= .env
ENV_FALLBACK ?= .env.example

.PHONY: build up down logs run-once shell validate

build:
	docker build -t $(IMAGE) .

up:
	@if [ -f "$(ENV_FILE)" ]; then \
		env_file="$(ENV_FILE)"; \
	elif [ -f "$(ENV_FALLBACK)" ]; then \
		env_file="$(ENV_FALLBACK)"; \
	else \
		echo "No env file found. Create $(ENV_FILE) or $(ENV_FALLBACK)."; \
		exit 1; \
	fi; \
	docker rm -f $(CONTAINER) >/dev/null 2>&1 || true; \
	docker run -d \
		--name $(CONTAINER) \
		--restart unless-stopped \
		--env-file "$${env_file}" \
		$(IMAGE)

down:
	docker rm -f $(CONTAINER) >/dev/null 2>&1 || true

logs:
	docker logs -f $(CONTAINER)

run-once:
	@if [ -f "$(ENV_FILE)" ]; then \
		env_file="$(ENV_FILE)"; \
	elif [ -f "$(ENV_FALLBACK)" ]; then \
		env_file="$(ENV_FALLBACK)"; \
	else \
		echo "No env file found. Create $(ENV_FILE) or $(ENV_FALLBACK)."; \
		exit 1; \
	fi; \
	docker run --rm \
		--env-file "$${env_file}" \
		$(IMAGE) \
		python -m grocy_recipe_import once

shell:
	@if [ -f "$(ENV_FILE)" ]; then \
		env_file="$(ENV_FILE)"; \
	elif [ -f "$(ENV_FALLBACK)" ]; then \
		env_file="$(ENV_FALLBACK)"; \
	else \
		echo "No env file found. Create $(ENV_FILE) or $(ENV_FALLBACK)."; \
		exit 1; \
	fi; \
	docker run --rm -it \
		--env-file "$${env_file}" \
		$(IMAGE) sh

validate:
	python -m compileall src

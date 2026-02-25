.PHONY: install run dry-run docker-up docker-down test lint

install:
	pip install -r requirements.txt
	playwright install chromium

run:
	python main.py

dry-run:
	python main.py --dry-run

dashboard:
	python main.py --dashboard-only

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f agent

test:
	pytest tests/ -v --tb=short

lint:
	python -m py_compile main.py agent/*.py platforms/*.py stealth/*.py dashboard/app.py
	@echo "✅ No syntax errors"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true

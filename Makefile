setup:
	curl -LsSf https://astral.sh/uv/install.sh | sh
	uv sync
	uv run pre-commit install
	source .venv/bin/activate
	modal setup
	git clone https://github.com/Len-Stevens/Python-Antivirus.git
	echo "export PYTHONPATH=.:$PYTHONPATH" >> ~/.bashrc
	echo "export TOKENIZERS_PARALLELISM=false" >> ~/.bashrc
	echo "export HF_HUB_ENABLE_HF_TRANSFER=1" >> ~/.bashrc
	source ~/.bashrc

migrate:
	$(eval MSG ?= )
	$(eval ENV ?= main)
	uv run alembic -x env=$(ENV) -c db/migrations/alembic.ini stamp head
	uv run alembic -x env=$(ENV) -c db/migrations/alembic.ini revision --autogenerate -m "$(MSG)" --version-path db/migrations/versions/$(ENV)
	uv run alembic -x env=$(ENV) -c db/migrations/alembic.ini upgrade head
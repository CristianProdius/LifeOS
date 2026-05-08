FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["sh", "-lc", "uvicorn lifeos_api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]

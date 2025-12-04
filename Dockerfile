FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev deps in production)
RUN poetry config virtualenvs.create false && poetry install --only main --no-root --no-interaction

# Copy application code
COPY src/ ./src/

EXPOSE 8787

# Run as non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "src.main"]

FROM python:3.12-slim

WORKDIR /app

# Copy uv binary from the official image — faster than pip for installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (separate layer so it caches between code changes)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

CMD ["python", "bot.py"]

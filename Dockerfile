# --- 1. Compila la web (web/dist no está en git) ---
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- 2. Servicio ---
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HCVRP_HOST=0.0.0.0 \
    PORT=8001 \
    HCVRP_DB=/app/data/hcvrp.db

# Dependencias primero, para que un cambio de código no las reinstale
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY --from=web /web/dist ./web/dist

EXPOSE 8001

# data/ (base y clients_laguna.json) y .cache/ llegan como volúmenes.
# El seed solo inserta lo que falta: correrlo en cada arranque no pisa lo editado en la app.
CMD ["sh", "-c", "python -m hcvrp.api.seed && exec python -m hcvrp.api"]

#  NAO API — Dockerfile
#  Image: python:3.11-slim (~50MB)
#zero external python dependencies

FROM python:3.11-slim AS base

#metadata
LABEL maintainer="nao-api" \
      description="NAO V5 <-> ChatGPT API Server" \
      version="1.0.0"

#timezone
ENV TZ=America/Sao_Paulo \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

#non root user for security
RUN groupadd -r naoapi && useradd -r -g naoapi -d /app naoapi

#working directory
WORKDIR /app

#copy code
COPY --chown=naoapi:naoapi app/         ./app/
COPY --chown=naoapi:naoapi .env.example ./.env.example

#create data and log permissions 
RUN mkdir -p data/sessions data/knowledge logs && \
    chown -R naoapi:naoapi data/ logs/

#switching to a non root user
USER naoapi

#exposed port
EXPOSE 8080

#health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)" \
    || exit 1

#entrypoint
CMD ["python3", "-u", "app/server.py"]

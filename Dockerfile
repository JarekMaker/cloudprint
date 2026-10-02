FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home agent
USER agent

# Mount certs at /certs; configure with PRINTER_ID, IOT_ENDPOINT, BACKEND, ...
ENV CERTS_DIR=/certs
ENTRYPOINT ["cloudprint-agent"]

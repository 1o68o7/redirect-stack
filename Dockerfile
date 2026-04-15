FROM python:3.11-slim

# System deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .

# Copy source
COPY redirectmap/ ./redirectmap/

# Data volumes: input files + output artefacts + SQLite DB
VOLUME ["/data/input", "/data/output", "/data/db"]

ENTRYPOINT ["redirectmap"]
CMD ["--help"]

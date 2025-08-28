FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /webapi

# Install Python dependencies
RUN pip install --upgrade pip uv
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 cosap && chown -R cosap:cosap /webapi
USER cosap

EXPOSE 8000
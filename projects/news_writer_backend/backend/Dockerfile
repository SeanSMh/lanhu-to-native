FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 基础系统依赖：postgres 客户端、编译 Pillow 所需
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
RUN pip install --upgrade pip && pip install -e .

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OIC_PROJECT_ROOT=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgdal-dev gdal-bin proj-data \
    && rm -rf /var/lib/apt/lists/*

ENV PROJ_LIB=/usr/share/proj \
    PROJ_DATA=/usr/share/proj

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8080
CMD ["uvicorn", "deploy.harvester_service.main:app", "--host", "0.0.0.0", "--port", "8080"]


FROM python:3.12-slim

WORKDIR /app

# Install curl for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV SERVICE_ROLE=all
ENV PORT=5001

EXPOSE 5001 5002 5003

CMD ["python", "app.py"]

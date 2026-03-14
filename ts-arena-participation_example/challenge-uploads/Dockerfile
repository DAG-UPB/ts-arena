
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	API_BASE_URL=http://api-portal:8000

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Run the script in continuous mode
CMD ["python", "src/main.py"]
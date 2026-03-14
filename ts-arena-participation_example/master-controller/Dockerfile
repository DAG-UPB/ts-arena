
FROM python:3.12-slim

RUN pip install --no-cache-dir docker

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

CMD ["python", "main.py"]
FROM python:3.12-slim

WORKDIR /app

COPY infra/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p data/memory

COPY src/ src/
COPY run_gateway.py .
COPY run_callback.py .

EXPOSE 18090 18091

CMD ["python3", "run_gateway.py"]

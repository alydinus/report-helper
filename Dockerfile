FROM python:3.12-slim

LABEL authors="alydinus"

WORKDIR /app

RUN pip install --no-cache-dir \
    google-auth \
    google-api-python-client \
    google-genai

COPY report.py ./

WORKDIR /config

ENTRYPOINT ["python", "/app/report.py"]

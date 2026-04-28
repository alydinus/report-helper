FROM python:3.12-slim

LABEL authors="alydinus"

WORKDIR /app

RUN pip install --no-cache-dir \
    google-auth \
    google-api-python-client \
    google-genai

COPY service-account.json report.py ./

ENTRYPOINT ["python", "report.py"]

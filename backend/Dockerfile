FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5100
WORKDIR /app

COPY pyproject.toml README.md ./
COPY codeverse ./codeverse
RUN pip install --no-cache-dir .

EXPOSE 5100
CMD ["python", "-m", "codeverse"]

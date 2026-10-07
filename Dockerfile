FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
RUN python -m pip install --no-cache-dir .
USER 1000:1000
CMD ["uvicorn", "sme_bridge.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir numpy pandas pyarrow networkx leuvenmapmatching catboost \
        fastapi "uvicorn[standard]" httpx

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY tools ./tools
COPY dashboard ./dashboard
COPY docs ./docs

RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000 8100 9201

CMD ["python", "-m", "mtp.api.main", "--mode", "combined"]

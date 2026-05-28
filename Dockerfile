# Multi-stage build. Prophet pulls cmdstanpy/Stan, so we compile in a builder
# stage and copy only the installed packages into a slim runtime image.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY service/requirements.txt service/requirements.txt
COPY core/ core/
COPY sim/ sim/
COPY service/ service/
# Install runtime deps + the project itself (editable not needed in container).
# This is what binds core/, sim/, service/ into the image as a real package set,
# so the service can import from them regardless of how the layout evolves.
RUN pip install --prefix=/install -r service/requirements.txt \
    && pip install --prefix=/install --no-deps .

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /install /usr/local

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
# Keep the source on disk for debugging; the installed package above is what
# Python actually imports. Mount /tmp and /app/.cmdstan as emptyDir at runtime
# to satisfy readOnlyRootFilesystem (Prophet/cmdstanpy writes there).
COPY service/ /app/
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

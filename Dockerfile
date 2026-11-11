# Image of the Streamlit interface (and of the indexing command, see docker-compose.yml).
# Python 3.13: the version used to test requirements.txt.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HOME=/home/app/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/home/app/.cache/fastembed \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# CPU build of PyTorch (same version as the tested environment). Without it, pip installs the
# CUDA build pulled by sentence-transformers, which adds several GB of unused GPU libraries.
ARG TORCH_VERSION=2.15.0
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"

COPY requirements.txt pyproject.toml ./
RUN pip install -r requirements.txt

COPY incident_assistant/ incident_assistant/
COPY app/ app/
# The PDFs are excluded by .dockerignore (licences); docker-compose.yml mounts the local knowledge base.
COPY knowledge_base/ knowledge_base/

# Editable install: incident_assistant/config.py locates knowledge_base/ and storage/ from the
# package folder, which must therefore stay in /app.
RUN pip install --no-deps -e . \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/storage /home/app/.cache/huggingface /home/app/.cache/fastembed \
    && chown -R app:app /app/storage /home/app/.cache

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]

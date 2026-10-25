# Backend image for Hugging Face Spaces (Docker SDK) or any container host. Build context: backend/.
# Python 3.14 is the version the code is written and tested on (it uses `except A, B:` without
# parentheses, which 3.13 refuses) and every pinned dependency ships a 3.14 Linux wheel.
FROM python:3.14-slim

# The container's disk is empty at every start; only /tmp (and /data, if persistent storage is
# switched on) is writable on Spaces, so the database defaults to /tmp. Override with DATABASE_URL.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/user \
    PORT=7860 \
    DATABASE_URL=sqlite:////tmp/happy-quanting.db

# Hugging Face runs the container as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user:user . .
# app/config.py makes this folder on import; it has to be ours to create.
RUN mkdir -p /app/data && chown user:user /app/data

USER user
EXPOSE 7860

# No --reload and no dev.py. The lifespan runs the migrations, the demo seed and the background
# loops. `exec` so uvicorn gets the stop signal.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]

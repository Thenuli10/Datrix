# analysis-runner:py3.12 - sandbox image for generated analysis code (PLAN.md §5).
# Built by backend/app/sandbox/manager.py:ensure_image(). The container runs with no network,
# a read-only root FS, all capabilities dropped and as uid 1000; only /output, /model (train)
# and the /tmp tmpfs are writable.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp \
    OMP_NUM_THREADS=2

# libgomp1: OpenMP runtime needed by lightgbm / xgboost.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/runner/requirements.txt
RUN pip install --no-cache-dir -r /opt/runner/requirements.txt && pip check

RUN groupadd --gid 1000 runner \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin runner

COPY runner.py /opt/runner/runner.py

USER 1000:1000
WORKDIR /tmp
ENTRYPOINT ["python", "/opt/runner/runner.py"]

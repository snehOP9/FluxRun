FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip
COPY alembic.ini ./
COPY alembic ./alembic
COPY fluxrun_api ./fluxrun_api
COPY fluxrun_worker ./fluxrun_worker
RUN pip install . && groupadd --system fluxrun && useradd --system --gid fluxrun --home-dir /app --no-create-home fluxrun && chown -R fluxrun:fluxrun /app
USER fluxrun
EXPOSE 8000

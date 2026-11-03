# syntax=docker/dockerfile:1
FROM python:3.13-slim-trixie@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install --no-install-recommends -y ca-certificates libmagic1 postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 recalltrace && useradd --uid 10001 --gid 10001 --create-home recalltrace
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=proxy_ca \
    set -eu; \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir --require-hashes -r requirements.txt; \
    python -m pip check; \
    # Installers and their vendored dependencies are not needed by the runtime.
    python -m pip uninstall --yes pip; \
    python -c 'import ensurepip, pathlib, shutil; shutil.rmtree(pathlib.Path(ensurepip.__file__).parent)'
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY wsgi.py gunicorn.conf.py ./
RUN chmod -R u=rwX,go=rX /app/app /app/migrations /app/scripts /app/wsgi.py /app/gunicorn.conf.py \
    && mkdir -p /app/instance && chown 10001:10001 /app/instance && chmod 700 /app/instance
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]

# syntax=docker/dockerfile:1
# Operator-only PostgreSQL clients. Build with --target database-tools; the web
# image never includes administrative clients or their operating-system packages.
FROM postgres:17-alpine@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b AS database-tools
# This stage executes clients directly as postgres, never the database daemon or
# its root-to-postgres privilege helper.
RUN rm -f /usr/local/bin/gosu /usr/local/bin/docker-entrypoint.sh /usr/local/bin/docker-ensure-initdb.sh \
    # Apply Alpine security fixes published after the pinned base image (e.g. zlib, krb5).
    && apk upgrade --no-cache
USER postgres
ENTRYPOINT []
CMD ["pg_dump", "--help"]

FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8 AS web
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# Apply Alpine security fixes published after the pinned base image (e.g. zlib).
RUN apk upgrade --no-cache \
    && addgroup -g 10001 recalltrace && adduser -D -u 10001 -G recalltrace recalltrace
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=proxy_ca \
    set -eu; \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.txt; \
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

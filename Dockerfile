# Railway runs the HTTP API, Django AAA policy engine, and the public RadSec
# gateway in one service so they share the same generated client PKI.
FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# FreeRADIUS terminates public mutual-TLS RadSec and proxies only to the
# Django AAA process over loopback UDP inside this container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends freeradius gettext-base openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
COPY deploy/radsec/entrypoint.sh /usr/local/bin/expressnet-radsec
COPY deploy/radsec/prepare-pki.sh /usr/local/bin/expressnet-prepare-radsec-pki
COPY deploy/radsec/railway-entrypoint.sh /usr/local/bin/expressnet-railway
COPY deploy/radsec/freeradius/clients.conf /etc/freeradius/3.0/clients.conf
COPY deploy/radsec/freeradius/proxy.conf /etc/freeradius/3.0/proxy.conf
COPY deploy/radsec/freeradius/sites-enabled/radsec /etc/freeradius/3.0/sites-enabled/radsec

RUN sed -i 's/\r$//' /usr/local/bin/expressnet-radsec /usr/local/bin/expressnet-prepare-radsec-pki /usr/local/bin/expressnet-railway \
    && chmod 0755 /usr/local/bin/expressnet-radsec /usr/local/bin/expressnet-prepare-radsec-pki /usr/local/bin/expressnet-railway \
    && rm -f /etc/freeradius/3.0/sites-enabled/default /etc/freeradius/3.0/sites-enabled/inner-tunnel

EXPOSE 8000 2083

CMD ["/usr/local/bin/expressnet-railway"]

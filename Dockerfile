FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# This is the Railway image: one service exposes the normal HTTP app and the
# raw TCP RadSec listener, sharing the same persistent PKI volume.
RUN apt-get update \
    && apt-get install -y --no-install-recommends freeradius gettext-base openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
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

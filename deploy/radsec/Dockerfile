FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# FreeRADIUS terminates public RadSec (TLS/TCP). The Django RADIUS policy
# process remains private on localhost UDP; deploy this image to a VPS that
# can expose the fixed TCP port 2083 required by RouterOS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends freeradius gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY deploy/radsec/entrypoint.sh /usr/local/bin/expressnet-radsec
COPY deploy/radsec/freeradius/clients.conf /etc/freeradius/3.0/clients.conf
COPY deploy/radsec/freeradius/proxy.conf /etc/freeradius/3.0/proxy.conf
COPY deploy/radsec/freeradius/sites-enabled/radsec /etc/freeradius/3.0/sites-enabled/radsec

RUN chmod 0755 /usr/local/bin/expressnet-radsec \
    && rm -f /etc/freeradius/3.0/sites-enabled/default /etc/freeradius/3.0/sites-enabled/inner-tunnel

EXPOSE 2083/tcp

CMD ["/usr/local/bin/expressnet-radsec"]

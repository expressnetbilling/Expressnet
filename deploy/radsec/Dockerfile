FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY deploy/radsec/entrypoint.sh /usr/local/bin/expressnet-radsec

RUN sed -i 's/\r$//' /usr/local/bin/expressnet-radsec \
    && chmod 0755 /usr/local/bin/expressnet-radsec

EXPOSE 1812/udp 1813/udp

CMD ["/usr/local/bin/expressnet-radsec"]

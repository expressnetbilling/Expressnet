# Railway runs the HTTP/API service. The standalone Railway RADIUS service
# owns the Django AAA listener.
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

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
COPY deploy/radsec/railway-entrypoint.sh /usr/local/bin/expressnet-railway

RUN sed -i 's/\r$//' /usr/local/bin/expressnet-railway \
    && chmod 0755 /usr/local/bin/expressnet-railway

EXPOSE 8000

CMD ["/usr/local/bin/expressnet-railway"]

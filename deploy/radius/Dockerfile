FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system expressnet && adduser --system --ingroup expressnet expressnet

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN chown -R expressnet:expressnet /app

USER expressnet

# The compose file selects the web, worker, beat, or RADIUS command. Keeping
# the image generic makes every service run the exact same application code.
CMD ["gunicorn", "billing_saas_django.wsgi:application", "--bind", "0.0.0.0:8000"]

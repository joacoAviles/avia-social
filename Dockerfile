FROM node:22.21.0-bookworm-slim AS frontend
WORKDIR /build/theme/static_src
COPY theme/static_src/ ./
COPY templates/ /build/templates/
COPY apps/ /build/apps/
RUN npm ci && npm run build
FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.avia
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ffmpeg libpq5 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
COPY --from=frontend /build/theme/static/css/dist/ /app/theme/static/css/dist/
RUN SECRET_KEY=build-only-not-a-runtime-secret DATABASE_URL=sqlite:////tmp/build.db python manage.py collectstatic --noinput && useradd --uid 10001 --create-home avia && mkdir -p /app/media && chown -R avia:avia /app/media
USER avia
EXPOSE 8000
CMD ["gunicorn","config.wsgi:application","--bind","0.0.0.0:8000","--workers","1","--threads","4"]

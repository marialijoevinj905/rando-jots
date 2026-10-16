FROM python:3.12-slim
# No third-party Python packages are needed; tzdata gives correct New York market hours.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY watchdesk ./watchdesk
COPY web ./web
COPY config.example.json portfolio.example.json ./
RUN useradd --create-home watch && mkdir -p /data && chown watch /data
USER watch
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
# /data holds config.json, portfolio.json and state/. Missing files fall back to the examples' defaults.
CMD ["sh", "-c", "[ -f /data/config.json ] || cp config.example.json /data/config.json; exec python -m watchdesk --config /data/config.json serve --host 0.0.0.0"]

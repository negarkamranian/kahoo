FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KAHOO_HOST=0.0.0.0 \
    KAHOO_PORT=4173

WORKDIR /app

RUN addgroup -S kahoo && adduser -S kahoo -G kahoo

COPY --chown=kahoo:kahoo server.py ./
COPY --chown=kahoo:kahoo backend ./backend
COPY --chown=kahoo:kahoo data ./data
COPY --chown=kahoo:kahoo public ./public

USER kahoo
EXPOSE 4173

CMD ["python3", "server.py"]

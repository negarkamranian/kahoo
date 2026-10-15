FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup -S kahoo && adduser -S kahoo -G kahoo

COPY --chown=kahoo:kahoo backend ./backend
COPY --chown=kahoo:kahoo db ./db
COPY --chown=kahoo:kahoo data ./data
COPY --chown=kahoo:kahoo public ./public
COPY --chown=kahoo:kahoo .env.example ./

USER kahoo

CMD ["python3", "-m", "backend", "serve"]

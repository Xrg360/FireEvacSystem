FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home app && mkdir -p uploads ml_models && chown -R app:app /srv
USER app

EXPOSE 5000
# One worker (Socket.IO needs sticky sessions for more); many threads for concurrent websockets.
CMD ["gunicorn", "-w", "1", "--threads", "100", "-b", "0.0.0.0:5000", "--timeout", "120", "wsgi:app"]

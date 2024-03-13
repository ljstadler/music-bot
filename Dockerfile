FROM python:alpine

COPY music-bot.py requirements.txt /.

RUN apk add --no-cache build-base libffi-dev && \
    pip install -r requirements.txt && \
    apk del build-base

CMD ["python", "music-bot.py"]
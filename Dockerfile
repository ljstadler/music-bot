FROM python:alpine

WORKDIR /music-bot

COPY music-bot.py requirements.txt ./

RUN apk add --no-cache build-base libffi-dev && \
    pip install  --no-cache-dir -r requirements.txt && \
    apk del build-base && \
    adduser -H -S nonroot

USER nonroot

ENTRYPOINT ["python", "music-bot.py"]
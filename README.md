# music-bot

## Lavalink Discord music bot

## Usage

### Docker Compose

```yaml
services:
    lavalink:
        container_name: lavalink
        image: ghcr.io/lavalink-devs/lavalink:latest-alpine
        restart: unless-stopped
        environment:
            - _JAVA_OPTIONS=-Xmx6G
            - SERVER_PORT=2333
            - LAVALINK_SERVER_PASSWORD=lavalink
        volumes:
            - ./application.yaml:/opt/Lavalink/application.yaml
            - ./plugins/:/opt/Lavalink/plugins/

    music-bot:
        container_name: music-bot
        image: ghcr.io/ljstadler/music-bot:latest
        environment:
            - LAVALINK_HOST=lavalink
            - LAVALINK_PORT=2333
            - LAVALINK_PASSWORD=lavalink
            - TOKEN=${TOKEN}
```

### Docker Run

```bash
docker run -d -e TOKEN="{TOKEN}" -e LAVALINK_HOST="{LAVALINK_HOST}" -e LAVALINK_PORT="{LAVALINK_PORT}" -e LAVALINK_PASSWORD="{LAVALINK_PASSWORD}" --name music-bot ghcr.io/ljstadler/music-bot
```

### Example application.yaml

```yaml
lavalink:
    plugins:
        - dependency: "dev.lavalink.youtube:youtube-plugin:x.x.x"
        - dependency: "com.github.topi314.lavasrc:lavasrc-plugin:x.x.x"
    server:
        sources:
            youtube: false

plugins:
    youtube:
        oauth:
            enabled: true
            refreshToken: ""
            skipInitialization: true
    lavasrc:
        sources:
            spotify: true
        spotify:
            clientId: ""
            clientSecret: ""
```

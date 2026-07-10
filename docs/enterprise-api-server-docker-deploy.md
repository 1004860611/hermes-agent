# Enterprise API Server Docker Deploy

This runbook records the current two-environment Hermes deployment on the
Alibaba Cloud server.

## Current Layout

Server:

```text
root@101.133.155.193
```

Image:

```text
hermes-agent:enterprise
```

Production:

```text
/opt/hermes-deploy-prod/docker-compose.yml
/opt/hermes-data-prod/.env
/opt/hermes-data-prod/config.yaml
container: hermes-prod
external API: http://101.133.155.193:8642
```

Test:

```text
/opt/hermes-deploy-test/docker-compose.yml
/opt/hermes-data-test/.env
/opt/hermes-data-test/config.yaml
container: hermes-test
external API: http://101.133.155.193:8643
```

Inside both containers, Hermes uses:

```text
HERMES_HOME=/opt/data
```

The environments are isolated by the bind mount:

```text
hermes-prod: /opt/hermes-data-prod -> /opt/data
hermes-test: /opt/hermes-data-test -> /opt/data
```

Do not change `HERMES_HOME` to the host path. Keep it as `/opt/data`.

## Production Compose

`/opt/hermes-deploy-prod/docker-compose.yml` should keep the existing fields
and point to the production data directory:

```yaml
services:
  gateway:
    image: hermes-agent:enterprise
    container_name: hermes-prod
    restart: unless-stopped
    network_mode: host
    env_file:
      - /opt/hermes-data-prod/.env
    volumes:
      - /opt/hermes-data-prod:/opt/data
    environment:
      - HERMES_HOME=/opt/data
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_PORT=8642
      - API_SERVER_KEY=${API_SERVER_KEY}
      - HERMES_HOTEL_API_BASE_URL=https://api.charmdeer.com
      - HERMES_HOTEL_API_TIMEOUT_SECONDS=300
    command: ["gateway", "run", "--replace"]
```

Production currently uses host networking, so Hermes itself must listen on
`8642`.

## Test Compose

`/opt/hermes-deploy-test/docker-compose.yml` should use a different container
name, test data directory, and external port:

```yaml
services:
  gateway:
    image: hermes-agent:enterprise
    container_name: hermes-test
    restart: unless-stopped
    ports:
      - "8643:8642"
    env_file:
      - /opt/hermes-data-test/.env
    volumes:
      - /opt/hermes-data-test:/opt/data
    environment:
      - HERMES_HOME=/opt/data
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_PORT=8642
      - API_SERVER_KEY=${API_SERVER_KEY}
      - HERMES_HOTEL_API_BASE_URL=https://dev.charmdeer.com
      - HERMES_HOTEL_API_TIMEOUT_SECONDS=300
    command: ["gateway", "run", "--replace"]
```

The test container uses bridge port mapping:

```text
host 8643 -> container 8642
```

Therefore the container-side `API_SERVER_PORT` must remain `8642`. If it is set
to `8643`, `curl http://127.0.0.1:8643/health` can fail with connection reset
because Docker forwards to container port `8642` while Hermes is listening on a
different port.

## Runtime Secrets And Config

Each environment has its own `.env` and `config.yaml`.

Production:

```bash
nano /opt/hermes-data-prod/.env
nano /opt/hermes-data-prod/config.yaml
```

Test:

```bash
nano /opt/hermes-data-test/.env
nano /opt/hermes-data-test/config.yaml
```

The API keys must be aligned:

```text
consumer HERMES_ENTERPRISE_API_KEY == Hermes API_SERVER_KEY
```

Do not commit real `.env` files. Use placeholders in documentation and example
files only.

## Consumer Configuration

Production consumer:

```env
HERMES_ENTERPRISE_BASE_URL=http://101.133.155.193:8642
HERMES_ENTERPRISE_API_KEY=<same-value-as-prod-API_SERVER_KEY>
```

Test consumer:

```env
HERMES_ENTERPRISE_BASE_URL=http://101.133.155.193:8643
HERMES_ENTERPRISE_API_KEY=<same-value-as-test-API_SERVER_KEY>
```

`server/env/dev.env` is ignored by Git. If a shareable template is needed,
create an example file without secrets, such as `server/env/dev.env.example`.

## Start And Stop

Production:

```bash
cd /opt/hermes-deploy-prod
docker compose up -d
docker logs --tail=100 hermes-prod
```

Test:

```bash
cd /opt/hermes-deploy-test
docker compose up -d
docker logs --tail=100 hermes-test
```

Stop one environment:

```bash
cd /opt/hermes-deploy-prod
docker compose down

cd /opt/hermes-deploy-test
docker compose down
```

## Health Checks

Production:

```bash
curl http://127.0.0.1:8642/health
```

Test:

```bash
curl http://127.0.0.1:8643/health
```

List containers:

```bash
docker ps | grep hermes
```

Expected containers:

```text
hermes-prod
hermes-test
```

## Enterprise Stream Smoke Tests

Production:

```bash
curl -N \
  -X POST http://127.0.0.1:8642/v1/enterprise/turn/stream \
  -H "Authorization: Bearer <prod-API_SERVER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "enterprise-hermes-consumer-v1",
    "requestId": "prod-debug-001",
    "user": {"id": "debug-user", "type": "user"},
    "session": {"id": "debug-session"},
    "message": {"role": "user", "content": "你好，简单回复一句话"},
    "runtimePolicy": {"allowedCapabilityRefs": []},
    "credentialBroker": {"credentialRef": "debug", "ttlSeconds": 300, "scope": []}
  }'
```

Test:

```bash
curl -N \
  -X POST http://127.0.0.1:8643/v1/enterprise/turn/stream \
  -H "Authorization: Bearer <test-API_SERVER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "enterprise-hermes-consumer-v1",
    "requestId": "test-debug-001",
    "user": {"id": "debug-user", "type": "user"},
    "session": {"id": "debug-session"},
    "message": {"role": "user", "content": "你好，简单回复一句话"},
    "runtimePolicy": {"allowedCapabilityRefs": []},
    "credentialBroker": {"credentialRef": "debug", "ttlSeconds": 300, "scope": []}
  }'
```

Success means the stream returns `event: delta` and final `event: done`.

## Persistent Data

Hermes persists workspaces, memory, sessions, logs, and model config under each
environment data directory:

```text
/opt/hermes-data-prod/
/opt/hermes-data-test/
```

Do not delete these directories during image updates.

Enterprise user data is stored under:

```text
/opt/hermes-data-*/enterprise/users/<user-id>/
```

Using separate data directories prevents test memory/session/workspace data from
polluting production.

## Troubleshooting

### Test health check returns connection reset

Check whether the test compose uses `ports: "8643:8642"` and whether Hermes is
listening on container port `8642`:

```bash
cd /opt/hermes-deploy-test
docker compose config
docker logs --tail=200 hermes-test
```

If `API_SERVER_PORT=8643` is set inside the test container, change it to
`API_SERVER_PORT=8642` or remove it.

### API 401

The consumer key and Hermes server key do not match. Check:

```bash
cd /opt/hermes-deploy-prod
docker compose config | grep API_SERVER_KEY

cd /opt/hermes-deploy-test
docker compose config | grep API_SERVER_KEY
```

Also check the consumer env file:

```text
HERMES_ENTERPRISE_API_KEY
```

### Model provider 401

Check whether the container can read the model provider key:

```bash
docker exec hermes-prod sh -lc 'python - <<PY
import os
for k in ["QWEN_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
    v = os.getenv(k)
    print(k, "present" if v else "missing", len(v) if v else 0)
PY'
```

Use `hermes-test` for the test environment.

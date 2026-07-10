# Hermes Enterprise Image Update Runbook

This runbook records how to rebuild the local Hermes enterprise image, upload it
to the Alibaba Cloud server, load it, and recreate both production and test
containers.

## Current Assumptions

Local source directory:

```text
E:\workspace\mongo-hu\hermes-agent
```

Image tag:

```text
hermes-agent:enterprise
```

Local exported image:

```text
E:\workspace\mongo-hu\hermes-agent-enterprise-image.tar
```

Remote server:

```text
root@101.133.155.193
```

Remote image tar:

```text
/opt/hermes-agent-enterprise-image.tar
```

Remote deployments:

```text
/opt/hermes-deploy-prod
/opt/hermes-deploy-test
```

Remote data directories:

```text
/opt/hermes-data-prod
/opt/hermes-data-test
```

Containers:

```text
hermes-prod
hermes-test
```

Ports:

```text
prod: http://101.133.155.193:8642
test: http://101.133.155.193:8643
```

## 1. Confirm Local Code State

In PowerShell:

```powershell
cd E:\workspace\mongo-hu\hermes-agent
git status
```

Make sure all intended Hermes code changes are present before building.

Do not bake local `.env`, API keys, or server runtime config into the image.
Runtime config belongs on the server under:

```text
/opt/hermes-data-prod/.env
/opt/hermes-data-prod/config.yaml
/opt/hermes-data-test/.env
/opt/hermes-data-test/config.yaml
```

## 2. Build The Image

```powershell
cd E:\workspace\mongo-hu\hermes-agent
docker build -t hermes-agent:enterprise .
```

Confirm the image exists:

```powershell
docker images hermes-agent:enterprise
```

## 3. Check s6 Type File Line Endings

This catches the previous CRLF problem that caused s6 startup failure:

```powershell
docker run --rm --entrypoint /bin/sh hermes-agent:enterprise -lc "od -An -tx1 -c /etc/s6-overlay/s6-rc.d/dashboard/type; cat -A /etc/s6-overlay/s6-rc.d/dashboard/type"
```

Expected output contains LF only:

```text
6c 6f 6e 67 72 75 6e 0a
l  o  n  g  r  u  n \n
longrun$
```

If output contains `0d 0a` or `^M`, fix line-ending handling in the Docker
build context and rebuild.

## 4. Save The Image To tar

```powershell
docker save hermes-agent:enterprise -o E:\workspace\mongo-hu\hermes-agent-enterprise-image.tar
```

Confirm the tar exists:

```powershell
Get-Item E:\workspace\mongo-hu\hermes-agent-enterprise-image.tar
```

## 5. Upload The Image To The Server

```powershell
scp E:\workspace\mongo-hu\hermes-agent-enterprise-image.tar root@101.133.155.193:/opt/
```

## 6. Load The Image On The Server

SSH to the server:

```powershell
ssh root@101.133.155.193
```

Then run:

```bash
docker load -i /opt/hermes-agent-enterprise-image.tar
docker images | grep hermes-agent
```

Notes:

- `docker load` updates the local `hermes-agent:enterprise` tag.
- Existing running containers do not automatically switch to the new image.
- Recreate containers after loading the new image.

## 7. Confirm Compose Files

Production:

```bash
cd /opt/hermes-deploy-prod
cat docker-compose.yml
docker compose config
```

Test:

```bash
cd /opt/hermes-deploy-test
cat docker-compose.yml
docker compose config
```

Important expected differences:

```text
prod container_name: hermes-prod
prod data volume: /opt/hermes-data-prod:/opt/data
prod external port: 8642

test container_name: hermes-test
test data volume: /opt/hermes-data-test:/opt/data
test external port: 8643
```

For the test environment using bridge networking, the compose port mapping
should be:

```yaml
ports:
  - "8643:8642"
```

In that case the container-side API server port remains `8642`.

## 8. Recreate Containers After Image Update

After `docker load`, the tag `hermes-agent:enterprise` points to the new image,
but already-running containers still use the old image id. Recreate the target
environment to switch it to the new image.

Recommended rollout order:

```text
1. Recreate test.
2. Verify test health and stream response.
3. Recreate production.
4. Verify production health and stream response.
```

### Update Test Only

Use this when validating a new image before production:

```bash
cd /opt/hermes-deploy-test
docker compose up -d --force-recreate
docker logs --tail=100 hermes-test
curl http://127.0.0.1:8643/health
```

### Update Production Only

Use this after the test environment has passed validation:

```bash
cd /opt/hermes-deploy-prod
docker compose up -d --force-recreate
docker logs --tail=100 hermes-prod
curl http://127.0.0.1:8642/health
```

### Update Both Environments

Use this only when you intentionally want both environments on the new image in
one maintenance window:

```bash
cd /opt/hermes-deploy-test
docker compose up -d --force-recreate

cd /opt/hermes-deploy-prod
docker compose up -d --force-recreate
```

If a container is stuck in an abnormal state:

```bash
docker rm -f hermes-test 2>/dev/null || true
cd /opt/hermes-deploy-test
docker compose up -d

docker rm -f hermes-prod 2>/dev/null || true
cd /opt/hermes-deploy-prod
docker compose up -d
```

## 9. View Logs

```bash
docker ps -a --filter name=hermes
docker logs --tail=200 hermes-prod
docker logs --tail=200 hermes-test
```

Follow logs:

```bash
docker logs -f hermes-prod
docker logs -f hermes-test
```

Normal startup should not show:

```text
s6-rc-compile: fatal: invalid .../type
```

## 10. Verify APIs

Production:

```bash
curl http://127.0.0.1:8642/health
```

Test:

```bash
curl http://127.0.0.1:8643/health
```

Enterprise stream smoke test:

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

Use port `8643` and the test API key for the test environment.

## 11. Consumer Access

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

Every request must include:

```http
Authorization: Bearer <API_SERVER_KEY>
```

## 12. Common Problems

### docker load succeeded but service still runs old code

The tag changed, but old containers still use the previous image id. Recreate
the containers:

```bash
cd /opt/hermes-deploy-prod
docker compose up -d --force-recreate

cd /opt/hermes-deploy-test
docker compose up -d --force-recreate
```

### API 401

Check that consumer `HERMES_ENTERPRISE_API_KEY` matches the target environment
`API_SERVER_KEY`.

```bash
cd /opt/hermes-deploy-prod
docker compose config | grep API_SERVER_KEY

cd /opt/hermes-deploy-test
docker compose config | grep API_SERVER_KEY
```

### Test health check returns connection reset

For test bridge networking, make sure:

```yaml
ports:
  - "8643:8642"
```

and the container-side API server port is `8642`, not `8643`.

### Model provider 401

Check whether the container can read the provider key:

```bash
docker exec hermes-prod sh -lc 'python - <<PY
import os
for k in ["QWEN_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
    v = os.getenv(k)
    print(k, "present" if v else "missing", len(v) if v else 0)
PY'
```

Use `hermes-test` for test.

### Clean dangling images

After both containers are healthy, optionally clean unused layers:

```bash
docker image prune -f
```

Do not delete:

```text
/opt/hermes-data-prod
/opt/hermes-data-test
```

They contain workspaces, memory, sessions, logs, and runtime config.

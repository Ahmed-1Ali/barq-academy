# Troubleshooting Journal

This journal records the actual investigation and repair work performed during the
BARQ DevOps assessment. Failed attempts are included only where they occurred
during the investigation.

## 1. Application readiness failure: missing PostgreSQL configuration

### Symptom
The application containers were running, but application readiness did not pass.
The application could not establish the expected PostgreSQL connection.

### Hypothesis
The PostgreSQL container itself might be unhealthy, PostgreSQL might not be
reachable over the Docker backend network, or the application might have incorrect
database configuration.

### Commands and tests

Checked the service state:

```bash
sudo docker compose ps

The PostgreSQL service was healthy and Redis was also available. The application
configuration was missing the required DATABASE_URL.

### Root cause

The application did not have the PostgreSQL connection string configured.

### Fix

Added the PostgreSQL connection string to the application environment:

DATABASE_URL=postgresql://barq_app:${POSTGRES_PASSWORD}@postgres:5432/barq_tasks

Redis was also configured explicitly:

REDIS_URL=redis://redis:6379/0

### Retest

Application readiness was checked again after recreating the application
containers. The application became ready and could communicate with PostgreSQL
and Redis.

### Commit

2809883 - Configure app resources and backend URLs

---

## 2. NGINX upstream failure and backend failover

### Symptom

When app-01 was stopped, requests through NGINX did not consistently fail over
to app-02.

### Initial test

Stopped app-01:

sudo docker stop app-01

Sent ten requests through NGINX:

for i in {1..10}; do
    curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/instance
done

The test produced both successful and failed responses, including 502 and 504.

### Failed attempt

Tried to reload NGINX while app-01 was stopped.

NGINX reported:

host not found in upstream "app-01:8080"

Further investigation showed that the app-01 Docker network endpoint was
temporarily inconsistent even though the container existed and appeared healthy.

### Root cause

There were two contributing problems:

1. The original NGINX configuration did not provide suitable upstream failure
   handling.
2. The Docker network endpoint for app-01 was inconsistent.

### Fix

Recreated only app-01:

sudo docker compose up -d --force-recreate app-01

The NGINX upstream configuration was updated to:

server app-01:8080 max_fails=2 fail_timeout=5s;
server app-02:8080 max_fails=2 fail_timeout=5s;

NGINX was also configured to retry suitable upstream failures:

proxy_next_upstream error timeout http_502 http_503 http_504;

### Verification

Checked the NGINX configuration:

sudo docker exec nginx nginx -t

Reloaded NGINX:

sudo docker exec nginx nginx -s reload

Stopped app-01 again and sent ten requests. All ten returned HTTP 200 through
app-02.

Restored app-01:

sudo docker start app-01

Both application instances returned to a healthy state and traffic was again
distributed between them.

### Commit

796514e - Improve NGINX upstream failover

---

## 3. Redis persistence failure

### Symptom

Redis used AOF persistence, but the counter value did not survive Redis container
recreation.

### Investigation

Checked Redis AOF configuration and its data directory:

sudo docker exec redis redis-cli CONFIG GET appendonly
sudo docker exec redis sh -c 'ls -la /data'

AOF was enabled, but /data was not backed by a persistent Docker volume.

### Root cause

AOF persistence inside the container does not preserve data when the container
filesystem is discarded.

### Fix

Added a named volume:

redis-data:/data

and declared the named volume in Compose.

### Verification

Redis was recreated while keeping the named volume. The counter value continued
from the previously persisted value after recreation.

### Commit

04b95ad - Persist Redis AOF in named volume

---

## 4. PostgreSQL backup and restore

### Symptom

The assessment required a PostgreSQL backup and a real restore demonstration.

### Backup

Created a backup with:

./backup.sh

The generated SQL backup was stored under backups/. The directory is excluded
from Git.

### Failed restore attempt

The backup was first restored directly into the existing barq_tasks database.

This produced expected conflicts because the schema and records already existed.
Errors included an existing relation, an existing sequence, duplicate primary
keys, and an existing primary key constraint.

### Clean restore

The application containers were stopped. The barq_tasks database was dropped
and recreated using the PostgreSQL owner. The backup was then restored into the
clean database.

The restored database contained the records that existed at backup time.
A record created after the backup was absent, proving that the restore returned
the database to the backup state.

### Verification

The application was restarted and /records was checked. The restored data was
available through the application.

### Commits

f88b64a - Implement PostgreSQL backup script

c5cac8d - Implement PostgreSQL restore script

---

## 5. PostgreSQL persistence across container recreation

### Test record

Created the following test record:

CONTAINER_RECREATE_TEST

### Test

The PostgreSQL container was stopped and removed without deleting its named
volume:

sudo docker stop postgres
sudo docker rm postgres

The named PostgreSQL volume remained present.

The PostgreSQL service was recreated:

sudo docker compose up -d postgres

### Verification

Checked PostgreSQL health:

sudo docker inspect postgres --format '{{.State.Health.Status}}'

Result:

healthy

Checked the test record through the public application endpoint:

curl -s http://127.0.0.1:8080/records | grep -o 'CONTAINER_RECREATE_TEST'

Result:

CONTAINER_RECREATE_TEST

### Conclusion

The record survived PostgreSQL container recreation because the database data is
stored in the named postgres-data volume rather than the disposable container
filesystem.

---

## 6. Validation script false failures

### Symptom

The first implementation of validate.py reported failures even though the
application and Docker environment were functioning correctly.

### Investigation

The validator used `sudo docker` commands. This worked in some environments
but failed in the assessment environment because Docker CLI access was already
available directly.

The validator also incorrectly treated an internal Docker port declaration such
as `8080/tcp` as a published host port. This could report a false failure for
the requirement that application, PostgreSQL, and Redis ports must not be
published to the host.

### Root cause

The validation script had two incorrect assumptions:

1. Docker CLI commands were unnecessarily prefixed with `sudo`.
2. Container ports were not distinguished from published host ports.

### Fix

The validator was corrected to:

- use the Docker CLI directly;
- distinguish internal container ports from published host ports;
- verify the actual NGINX public binding;
- validate Docker network membership;
- validate backend network isolation;
- check service health and application readiness;
- verify both application instances receive traffic.

### Verification

The corrected validation script was executed successfully:

=== VALIDATION PASSED ===
All required checks passed.

The same validation script also passed in GitHub Actions after the fix.

### Commit

ce76f89 - Sala7t el validation script 3ashan yesta5dem Docker CLI 3ala tool badal ma ye3tamed 3ala sudo

---

## 7. Backend failure and recovery test

### Test

The failure test measured traffic before, during, and after stopping one backend.

Baseline:

20/20 successful requests
app-01: 9
app-02: 11
errors: 0

During app-01 failure:

20/20 successful requests
app-02: 20
errors: 0

After recovery:

20/20 successful requests
app-01: 10
app-02: 10
errors: 0

### Conclusion

NGINX successfully continued serving traffic through app-02 while app-01 was
unavailable. After recovery, traffic returned to both application instances.

### Commit

d906c2b - Implement backend failure recovery test

---

## 8. Current PostgreSQL persistence retest

The PostgreSQL container was recreated while preserving the named volume.

The service was brought back with:

sudo docker compose up -d postgres

Health was verified:

sudo docker inspect postgres --format '{{.State.Health.Status}}'

Result:

healthy

The persistence record was then checked:

curl -s http://127.0.0.1:8080/records | grep -o 'CONTAINER_RECREATE_TEST'

Result:

CONTAINER_RECREATE_TEST

This confirms the persistence test remains valid after the latest PostgreSQL
container recreation.

---

## Conclusion

The major runtime issues investigated during the assessment were:

- missing application PostgreSQL configuration;
- NGINX upstream failover behavior;
- an inconsistent Docker network endpoint;
- Redis persistence without a volume;
- PostgreSQL restore into a non-empty database;
- PostgreSQL container recreation and persistence;
- false failures in the first validation implementation.

Each issue was investigated with commands and observable results before the
corresponding fix was applied. Successful fixes were retested and committed.

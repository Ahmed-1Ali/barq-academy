# Log analysis

This analysis uses all three supplied logs: `access.log`, `error.log`, and `application.log`. The original log files were analyzed without modification.

## 1. What UTC interval is covered? How many valid, malformed and duplicate lines are in each file?

### UTC interval

The access log covers:

* Start: `2026-08-20T11:00:00.015Z`
* End: `2026-08-20T11:29:57.578Z`

Therefore, the observed interval is approximately 30 minutes.

### access.log

```text
Total lines:       726
Valid JSON lines:  725
Malformed lines:   1
Duplicate records: 5
Distinct requests: 720
```

The malformed line is line 311:

```text
{"timestamp":"2026-08-20T11:12:48Z","request_id":
```

The duplicate request IDs are:

```text
lab-000121
lab-000241
lab-000361
lab-000481
lab-000601
```

Each of these appears twice with identical timestamps, paths, status, upstream, and request time. All five duplicate records have status `200`.

### application.log

```text
Total lines:       730
Valid JSON lines:  729
Malformed lines:   1
```

The malformed line is line 401:

```text
{"timestamp":"2026-08-20T11:17:00Z","event":
```

The application log has no exact duplicate records. The same request ID can appear in multiple events for one request.
ya3ny malafat el Application Log mafihosh records metkarra bel shakl el motabe2, bas momken nafs el Request ID yezhar fe aktar men Event le nafs el Request

### error.log

```text
Total lines: 68
```

The error log contains NGINX error events rather than one record per client request, so its line count should not be interpreted as the number of client failures.

### Commands used

```bash
wc -l access.log error.log application.log
```

JSON validation was performed with Python:

```bash
python3 - <<'PY'
import json

for filename in ["access.log", "application.log"]:
    valid = 0
    malformed = 0

    with open(filename) as f:
        for line in f:
            try:
                json.loads(line)
                valid += 1
            except json.JSONDecodeError:
                malformed += 1

    print(filename, "valid:", valid, "malformed:", malformed)
PY
```

---

## 2. How many distinct client requests occurred? How did you deduplicate and avoid counting retries twice?

There were **720 distinct client requests**.

The access log contains 725 valid JSON records. Five request IDs occurred twice:

```text
lab-000121
lab-000241
lab-000361
lab-000481
lab-000601
```

The duplicate records were exact duplicates and all represented successful `200` requests.

Therefore:

```text
725 valid access records - 5 duplicate records = 720 distinct requests
```

Upstream retries were not counted as additional client requests.

For example:

```text
upstream_status: "502, 200"
```

represents one client request where NGINX first received a `502` from one upstream and then successfully retried another upstream.

There were **19 such retry records**.

These 19 requests are already included in the final `200` count and were therefore not counted twice.

---

## 3. What are the final client status counts and error rate? State your denominator.

After removing the five duplicate access records, the final client status counts are:

| Status    |   Count |
| --------- | ------: |
| 200       |     615 |
| 404       |      10 |
| 502       |      40 |
| 503       |      47 |
| 504       |       8 |
| **Total** | **720** |

### 5xx error rate

I define a server error as an HTTP status in the `500–599` range.

```text
5xx requests = 40 + 47 + 8
             = 95

5xx error rate = 95 / 720 × 100
               = 13.19%
```

Therefore, the **5xx error rate is 13.19%** using 720 distinct client requests as the denominator.

### Non-2xx rate

If all responses with status `>= 400` are considered errors:

```text
Non-2xx = 10 + 40 + 47 + 8
        = 105

Non-2xx rate = 105 / 720 × 100
             = 14.58%
```

The 404 responses represent client-side missing-resource requests and are therefore reported separately from server failures.

---

## 4. Which paths, time windows and backends account for the failures?

### Failures by path

The final 5xx failures are distributed as follows:

| Path       | 5xx failures |
| ---------- | -----------: |
| `/records` |           26 |
| `/counter` |           26 |
| `/ready`   |           23 |
| `/health`  |           10 |
| `/`        |           10 |
| **Total**  |       **95** |

### Incident 1 — app-02 connectivity failure

The first major incident starts around:

```text
2026-08-20 11:05
```

NGINX error logs show:

```text
connect() failed (111: Connection refused) while connecting to upstream
```

The affected upstream was:

```text
172.23.0.12:8080
```

The access log shows `502` responses during this period.

Other requests were successfully served by:

```text
172.23.0.11:8080
```

There were also 19 requests with:

```text
upstream_status: "502, 200"
```

showing successful recovery through an upstream retry.

### Incident 2 — Redis dependency failure

The application dependency errors begin around:

```text
2026-08-20 11:12:09
```

There were:

```text
31 Redis dependency errors
```

They affected both application instances:

```text
app-01
app-02
```

The recorded dependency type was:

```text
redis
```

and the error type was `TimeoutError`.

The corresponding application requests returned `503`.

### Incident 3 — PostgreSQL dependency failure

PostgreSQL dependency errors begin around:

```text
2026-08-20 11:20:07
```

There were:

```text
16 PostgreSQL dependency errors
```

They affected both:

```text
app-01
app-02
```

The recorded PostgreSQL error type was:

```text
InvalidPassword
```

The corresponding application requests returned `503`.

### Incident 4 — upstream timeout

At approximately:

```text
2026-08-20 11:25–11:26
```

NGINX recorded:

```text
upstream timed out (110: Operation timed out) while reading response header from upstream
```

The affected requests were `/records` requests and produced client `504` responses.

---

## 5. What are the median and p95 client latencies? State the percentile method and units.

The request-time values in `access.log` were analyzed using valid JSON records.

Results:

```text
Minimum: 0.003 seconds
Median:  0.054 seconds
p95:     2.001 seconds
Maximum: 2.025 seconds
```

Therefore:

* Median = **54 ms**
* p95 = **2001 ms**

The percentile calculation used sorted request-time values and linear interpolation at:

```text
(n - 1) × p
```

where `p` is the percentile expressed as a fraction.

The p95 near two seconds is consistent with the observed upstream timeout/failure behavior.

---

## 6. Which requests retried upstream? How many succeeded after retrying?

There were **19 requests that retried upstream**.

They are identifiable by:

```text
upstream_status = "502, 200"
```

For example:

Awal mo7awala leltalab fashlet, bas NGINX 3amel retry w nege7et el mo7awala el tanyia, fa el most5dem estalam response naga7a

The retry pattern is identified by access-log records with:

upstream_status = "502, 200"

This means the first upstream attempt failed with `502`, and NGINX retried another upstream which returned `200`.

Therefore:

```text
Requests retried:              19
Successful after retry:        19

---

## 7. Build an incident timeline using evidence from access, error AND application logs.

### 11:00 — Normal traffic

Requests are successfully handled by both application instances.

The first request is:

```text
lab-000001
2026-08-20T11:00:00.015Z
GET /missing
404
```

The 404 is an expected missing-resource response rather than an infrastructure failure.

### 11:05 — app-02 connectivity failure begins

At:

```text
2026-08-20T11:05:00.055Z
```

`lab-000121` is successfully served by app-01.

Shortly afterward:

```text
lab-000122
GET /health
502
```

NGINX error logs show:

```text
connect() failed (111: Connection refused) while connecting to upstream
```

against:

```text
172.23.0.12:8080
```

This establishes a connectivity failure between NGINX and the affected upstream.

### 11:05–11:09 — NGINX retries healthy upstream

Requests continue to be served by app-01 while app-02 is unavailable.
Ya3ny en el Requestat betefdal troo7 3ala app-01 7atta law app-02 mesh sh8al

Several access records show:

```text
502, 200
```

indicating that the first upstream failed and NGINX successfully retried another backend.

A total of 19 requests succeeded after retry.

### 11:12 — Redis failures begin

The application log records:

```text
lab-000292
app-02
redis
TimeoutError
```

followed by similar failures on both app instances.

This continues through approximately 11:15.

There are 31 Redis dependency errors in total.

The application responds with `503`.

### 11:17 — malformed application-log record

Application log line 401 is malformed:

```text
{"timestamp":"2026-08-20T11:17:00Z","event":
```

This line cannot be used for structured event analysis.

### 11:20 — PostgreSQL failures begin

The application log records:

```text
lab-000484
app-02
postgres
InvalidPassword
```

followed by corresponding failures on app-01 and app-02.

There are 16 PostgreSQL dependency errors.

The application responds with `503`.

### 11:25–11:26 — `/records` upstream timeouts

NGINX reports:

```text
upstream timed out (110: Operation timed out) while reading response header from upstream
```

for `/records`.

The client receives `504`.

The timeout affects both upstream addresses in different requests.

### 11:29 — normal traffic resumes in observed logs

The final access record is:

```text
lab-000720
2026-08-20T11:29:57.578Z
GET /
200
```

served successfully.

---

## 8. Show one correlated failed request and one successful request. Include IDs and timestamps.

### Failed request

A clear proxy-level failure is:

```text
Request ID: lab-000122
Timestamp:  2026-08-20T11:05:02...
Path:       /health
Client:     502
Upstream:   172.23.0.12:8080
```

The corresponding NGINX error log reports:

```text
connect() failed (111: Connection refused) while connecting to upstream
```

This correlates the client `502` with a connection failure to the upstream.

### Successful retry

A clear successful-after-retry example is:

```text
Request ID: lab-000124
Timestamp: 2026-08-20T11:05:07.620Z
Path:       /ready
Client:     200
Upstream:   172.23.0.12:8080, 172.23.0.11:8080
Upstream status:
            502, 200
Request time:
            0.120 seconds
```

This proves that the first upstream attempt failed and the second upstream attempt succeeded.

The application-side request was ultimately successful, while NGINX recorded the failed first attempt.

---

## 9. Which errors appear to be proxy/connectivity issues versus dependency/application issues? What proves it?

### Proxy/connectivity issues

The strongest evidence is the 11:05–11:09 incident.

NGINX reports:

```text
connect() failed (111: Connection refused) while connecting to upstream
```

and identifies:

```text
172.23.0.12:8080
```

The access log shows client `502` responses.

The retry records show:

```text
502, 200
```

Therefore, this incident is consistent with an NGINX-to-upstream connectivity failure.

The later 11:25–11:26 failures show:

```text
upstream timed out (110: Operation timed out)
while reading response header from upstream
```

with client `504` responses.

These are also proxy/upstream communication or upstream responsiveness failures.

### Dependency/application issues

The application log directly records:

```text
31 Redis TimeoutError
16 PostgreSQL InvalidPassword
```

Both application instances are affected.

These requests result in application-level `503` responses.

This distinguishes the dependency incidents from the NGINX connection-refused incident because the application itself is producing the `503` responses after detecting dependency problems.

---

## 10. What do the logs not prove? What would you check next in a running environment?

The logs provide strong evidence about observed symptoms and correlations, but they do not prove the underlying infrastructure cause of every incident.

### The logs do not prove:

1. Why `172.23.0.12:8080` refused connections.
2. Whether the application process crashed, restarted, or was intentionally stopped.
3. The exact root cause of the Redis `TimeoutError`.
4. Why PostgreSQL authentication failed.
5. Whether the PostgreSQL password was changed, expired, misconfigured, or incorrectly supplied.
6. The exact cause of the `/records` upstream timeout.
7. Whether resource exhaustion such as CPU or memory contributed to the timeouts.
8. Whether network packet loss occurred.
9. Whether the malformed log lines were caused by concurrent writes, log corruption, or an upstream log-generation problem.
10. Whether all observed errors represent independent client requests because access-log duplicates exist.

### Checks I would perform in a running environment

For the affected application instance:

```bash
docker compose ps
docker inspect app-01
docker logs app-01
docker stats app-01
```

Check application restart history and health:

```bash
docker inspect app-01 --format '{{json .State}}'
```

Check connectivity and DNS from NGINX:

```bash
docker exec nginx getent hosts app-01
docker exec nginx getent hosts app-02
docker exec nginx wget -qO- http://app-01:8080/health
docker exec nginx wget -qO- http://app-02:8080/health
```

Check Redis:

```bash
docker exec redis redis-cli ping
docker logs redis
```

Check PostgreSQL:

```bash
docker exec postgres pg_isready -U barq_app -d barq_tasks
docker logs postgres
```

Check resource pressure:

```bash
docker stats
```

Check network configuration:

```bash
docker network inspect barq-assessment_frontend
docker network inspect barq-assessment_backend
```

For the `/records` timeout, I would additionally inspect application timing, PostgreSQL query execution, locks, connection availability, and container CPU/memory usage.

---

# Commands / scripts

The following commands were used during analysis.

### Count log lines

```bash
wc -l access.log error.log application.log
```

### Validate JSON

```bash
python3 - <<'PY'
import json

for filename in ["access.log", "application.log"]:
    valid = 0
    malformed = 0

    with open(filename) as f:
        for line in f:
            try:
                json.loads(line)
                valid += 1
            except json.JSONDecodeError:
                malformed += 1

    print(filename, valid, malformed)
PY
```

### Find duplicate request IDs

```bash
grep -o '"request_id":"[^"]*"' access.log |
sort |
uniq -d
```

### Count Redis and PostgreSQL dependency errors

```bash
grep -c '"dependency": "redis"' application.log
grep -c '"dependency": "postgres"' application.log
```

Results:

```text
Redis:     31
PostgreSQL: 16
```

### Status counts

```bash
python3 - <<'PY'
import json
from collections import Counter

c = Counter()

with open("access.log") as f:
    for line in f:
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue
        c[x["status"]] += 1

print(c)
PY
```

### Path/failure analysis

```bash
python3 - <<'PY'
import json
from collections import Counter

c = Counter()

with open("access.log") as f:
    for line in f:
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue

        if x["status"] >= 500:
            c[x["path"]] += 1

for path, count in c.most_common():
    print(path, count)
PY
```

### Dependency timeline

```bash
python3 - <<'PY'
import json

with open("application.log") as f:
    for line in f:
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue

        if x.get("event") == "dependency_error":
            print(
                x.get("timestamp"),
                x.get("request_id"),
                x.get("instance_id"),
                x.get("dependency")
            )
PY
```

---

# Results

The combined analysis found:

```text
Access log:
  726 total lines
  725 valid JSON
  1 malformed
  5 duplicate records
  720 distinct client requests

Application log:
  730 total lines
  729 valid JSON
  1 malformed

Error log:
  68 lines

Final client statuses:
  200 = 615
  404 = 10
  502 = 40
  503 = 47
  504 = 8

5xx errors:
  95 / 720 = 13.19%

Non-2xx responses:
  105 / 720 = 14.58%

Upstream retries:
  19
  Successful after retry: 19

Application dependency errors:
  Redis = 31
  PostgreSQL = 16

Latency:
  Median = 54 ms
  p95 = 2001 ms
  Minimum = 3 ms
  Maximum = 2025 ms
```

---

# Timeline and correlated examples

The logs indicate four main periods of abnormal behavior:

1. **11:05–11:09:** NGINX connection failures to `172.23.0.12:8080`, resulting in `502` responses and successful retries to the other backend.
2. **11:12–11:15:** Redis timeouts affecting both application instances, resulting in application-level `503` responses.
3. **11:20–11:21:** PostgreSQL authentication failures affecting both application instances, resulting in application-level `503` responses.
4. **11:25–11:26:** `/records` upstream response-header timeouts, resulting in `504` responses.

The logs therefore show both **proxy/upstream failures** and **application dependency failures** rather than a single common error type.

---

# Conclusions and limits

The strongest evidence is that the environment experienced multiple independent failure modes.

The first failure was a connectivity problem between NGINX and one application backend. NGINX received connection-refused errors from `172.23.0.12:8080`, while other requests were successfully served by the second backend. NGINX retries successfully handled 19 requests.

A later incident involved Redis timeouts affecting both application instances. Another involved PostgreSQL authentication failures affecting both instances. These produced application-level `503` responses and are therefore distinct from the earlier NGINX connectivity failure.

Finally, `/records` requests experienced upstream response-header timeouts and produced `504` responses.

The logs provide sufficient evidence to identify the affected layer and correlate client responses with proxy and application events. However, they do not by themselves prove the underlying infrastructure cause of every failure. Container state, application logs, dependency health, resource utilization, network state, and database/Redis logs would need to be inspected in a running environment to establish those deeper causes.

Malformed log records were excluded from structured analysis, and exact duplicate access records were deduplicated by `request_id` and identical record contents. Upstream retries were treated as attempts belonging to a single client request rather than additional client requests.


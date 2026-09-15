#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = 3
WAIT_SECONDS = 30

failures = []


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}" + (f" - {detail}" if detail else ""))
    else:
        print(f"FAIL: {name}" + (f" - {detail}" if detail else ""))
        failures.append(name)


def http_get(path):
    url = BASE_URL + path

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return response.status, body, dict(response.headers)

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""

        return exc.code, body, dict(exc.headers)

    except Exception as exc:
        return None, str(exc), {}


def wait_for_public_access():
    deadline = time.monotonic() + WAIT_SECONDS

    while time.monotonic() < deadline:
        status, _, _ = http_get("/health")

        if status == 200:
            return True

        time.sleep(1)

    return False


def container_health(container):
    code, output, error = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}",
            container,
        ]
    )

    if code != 0:
        return False, error or "docker inspect failed"

    return output == "healthy", output


def container_running(container):
    code, output, error = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}",
            container,
        ]
    )

    if code != 0:
        return False, error or "docker inspect failed"

    return output == "running", output


def get_container_ports(container):
    code, output, error = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Ports}}",
            container,
        ]
    )

    if code != 0:
        return None, error or "docker inspect failed"

    try:
        return json.loads(output), None
    except json.JSONDecodeError:
        return None, f"invalid port data: {output}"


def has_host_port(port_data):
    """
    Docker reports internal container ports such as:

        {"8080/tcp": null}

    when the port is NOT published to the host.

    A real host binding looks like:

        {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
    """

    if not isinstance(port_data, dict):
        return False

    for bindings in port_data.values():
        if isinstance(bindings, list) and bindings:
            return True

    return False


def get_networks(container):
    code, output, error = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Networks}}",
            container,
        ]
    )

    if code != 0:
        return None, error or "docker inspect failed"

    try:
        return json.loads(output), None
    except json.JSONDecodeError:
        return None, f"invalid network data: {output}"


def get_network_internal(network):
    code, output, error = run_command(
        [
            "docker",
            "network",
            "inspect",
            "-f",
            "{{.Internal}}",
            network,
        ]
    )

    if code != 0:
        return None, error or "docker network inspect failed"

    return output.lower() == "true", None


def network_endpoint_is_active(networks, expected):
    if not isinstance(networks, dict):
        return False

    network = networks.get(expected)

    if not isinstance(network, dict):
        return False

    endpoint_id = network.get("EndpointID")
    ip_address = network.get("IPAddress")

    return bool(endpoint_id and ip_address)


def main():
    print("=== BARQ Environment Validation ===")
    print(f"Base URL: {BASE_URL}")
    print()

    # ------------------------------------------------------------
    # 1. Required containers
    # ------------------------------------------------------------
    print("--- Container health ---")

    required_containers = [
        "nginx",
        "app-01",
        "app-02",
        "postgres",
        "redis",
    ]

    for container in required_containers:

        if container == "nginx":
            running, detail = container_running(container)

            check(
                "nginx running",
                running,
                detail,
            )

            continue

        healthy, detail = container_health(container)

        check(
            f"{container} health",
            healthy,
            detail,
        )

    print()

    # ------------------------------------------------------------
    # 2. Public access
    # ------------------------------------------------------------
    print("--- Public access ---")

    accessible = wait_for_public_access()

    check(
        "NGINX public access",
        accessible,
        BASE_URL,
    )

    if not accessible:
        print(
            "\nValidation cannot continue because the public endpoint "
            "is unavailable."
        )
        sys.exit(1)

    print()

    # ------------------------------------------------------------
    # 3. Required HTTP endpoints
    # ------------------------------------------------------------
    print("--- HTTP endpoints ---")

    expected_endpoints = [
        "/",
        "/health",
        "/ready",
        "/instance",
        "/records",
        "/counter",
    ]

    for path in expected_endpoints:

        status, body, _ = http_get(path)

        check(
            f"GET {path}",
            status == 200,
            f"HTTP {status}" if status is not None else body,
        )

    print()

    # ------------------------------------------------------------
    # 4. Readiness dependencies
    # ------------------------------------------------------------
    print("--- Dependency readiness ---")

    status, body, _ = http_get("/ready")

    ready_ok = False
    postgres_ready = False
    redis_ready = False

    if status == 200:

        try:
            data = json.loads(body)
            dependencies = data.get("dependencies", {})

            postgres_ready = (
                dependencies.get("postgres") == "ready"
            )

            redis_ready = (
                dependencies.get("redis") == "ready"
            )

            ready_ok = data.get("status") == "ready"

        except json.JSONDecodeError:
            pass

    check(
        "Application readiness",
        ready_ok,
        f"HTTP {status}",
    )

    check(
        "PostgreSQL readiness",
        postgres_ready,
    )

    check(
        "Redis readiness",
        redis_ready,
    )

    print()

    # ------------------------------------------------------------
    # 5. Verify both application instances receive traffic
    # ------------------------------------------------------------
    print("--- Load balancing ---")

    instances_seen = set()
    request_errors = 0

    for _ in range(12):

        status, body, headers = http_get("/instance")

        if status != 200:
            request_errors += 1
            continue

        instance_id = headers.get("X-Instance-ID")

        if not instance_id:

            try:
                data = json.loads(body)
                instance_id = data.get("instance_id")

            except json.JSONDecodeError:
                instance_id = None

        if instance_id:
            instances_seen.add(instance_id)

    check(
        "app-01 receives traffic",
        "app-01" in instances_seen,
        f"instances seen: {sorted(instances_seen)}",
    )

    check(
        "app-02 receives traffic",
        "app-02" in instances_seen,
        f"instances seen: {sorted(instances_seen)}",
    )

    check(
        "Load-balancer requests succeed",
        request_errors == 0,
        f"errors: {request_errors}",
    )

    print()

    # ------------------------------------------------------------
    # 6. Prohibited host ports
    # ------------------------------------------------------------
    print("--- Host port exposure ---")

    app_ports, app_error = get_container_ports("app-01")
    app2_ports, app2_error = get_container_ports("app-02")
    postgres_ports, postgres_error = get_container_ports("postgres")
    redis_ports, redis_error = get_container_ports("redis")
    nginx_ports, nginx_error = get_container_ports("nginx")

    app_has_host_port = (
        has_host_port(app_ports)
        if app_ports is not None
        else True
    )

    app2_has_host_port = (
        has_host_port(app2_ports)
        if app2_ports is not None
        else True
    )

    postgres_has_host_port = (
        has_host_port(postgres_ports)
        if postgres_ports is not None
        else True
    )

    redis_has_host_port = (
        has_host_port(redis_ports)
        if redis_ports is not None
        else True
    )

    nginx_has_port = (
        has_host_port(nginx_ports)
        if nginx_ports is not None
        else False
    )

    check(
        "app-01 has no host ports",
        app_ports is not None and not app_has_host_port,
        app_error or str(app_ports),
    )

    check(
        "app-02 has no host ports",
        app2_ports is not None and not app2_has_host_port,
        app2_error or str(app2_ports),
    )

    check(
        "postgres has no host ports",
        postgres_ports is not None and not postgres_has_host_port,
        postgres_error or str(postgres_ports),
    )

    check(
        "redis has no host ports",
        redis_ports is not None and not redis_has_host_port,
        redis_error or str(redis_ports),
    )

    check(
        "NGINX exposes the public port",
        nginx_has_port,
        nginx_error or str(nginx_ports),
    )

    print()

    # ------------------------------------------------------------
    # 7. Network isolation
    # ------------------------------------------------------------
    print("--- Network isolation ---")

    app01_networks, error = get_networks("app-01")
    app02_networks, error2 = get_networks("app-02")
    nginx_networks, error3 = get_networks("nginx")
    postgres_networks, error4 = get_networks("postgres")
    redis_networks, error5 = get_networks("redis")

    frontend = "barq-assessment_frontend"
    backend = "barq-assessment_backend"

    check(
        "app-01 is on frontend",
        network_endpoint_is_active(app01_networks, frontend),
        error or str(app01_networks),
    )

    check(
        "app-01 is on backend",
        network_endpoint_is_active(app01_networks, backend),
        error or str(app01_networks),
    )

    check(
        "app-02 is on frontend",
        network_endpoint_is_active(app02_networks, frontend),
        error2 or str(app02_networks),
    )

    check(
        "app-02 is on backend",
        network_endpoint_is_active(app02_networks, backend),
        error2 or str(app02_networks),
    )

    check(
        "NGINX is on frontend",
        network_endpoint_is_active(nginx_networks, frontend),
        error3 or str(nginx_networks),
    )

    check(
        "PostgreSQL is backend-only",
        network_endpoint_is_active(postgres_networks, backend)
        and len(postgres_networks) == 1,
        error4 or str(postgres_networks),
    )

    check(
        "Redis is backend-only",
        network_endpoint_is_active(redis_networks, backend)
        and len(redis_networks) == 1,
        error5 or str(redis_networks),
    )

    backend_internal, backend_error = get_network_internal(backend)

    check(
        "Backend network is internal",
        backend_internal is True,
        backend_error or str(backend_internal),
    )

    print()

    # ------------------------------------------------------------
    # 8. Functional checks
    # ------------------------------------------------------------
    print("--- Functional checks ---")

    status, body, _ = http_get("/records")

    records_ok = False

    if status == 200:

        try:
            data = json.loads(body)
            records_ok = isinstance(
                data.get("records"),
                list,
            )

        except json.JSONDecodeError:
            pass

    check(
        "PostgreSQL records endpoint",
        records_ok,
        f"HTTP {status}",
    )

    status, body, _ = http_get("/counter")

    counter_ok = False

    if status == 200:

        try:
            data = json.loads(body)
            counter_ok = isinstance(
                data.get("counter"),
                int,
            )

        except json.JSONDecodeError:
            pass

    check(
        "Redis counter endpoint",
        counter_ok,
        f"HTTP {status}",
    )

    print()

    # ------------------------------------------------------------
    # Final result
    # ------------------------------------------------------------
    if failures:

        print("=== VALIDATION FAILED ===")
        print(f"Failures: {len(failures)}")

        for failure in failures:
            print(f" - {failure}")

        sys.exit(1)

    print("=== VALIDATION PASSED ===")
    print("All required checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

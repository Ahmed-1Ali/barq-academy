#!/usr/bin/env python3

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8080"
REQUEST_COUNT = 20
REQUEST_TIMEOUT = 3
HEALTH_WAIT = 30

failures = []


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def docker_state(container):
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
        return ""
    return output


def docker_health(container):
    code, output, error = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Health.Status}}",
            container,
        ]
    )
    if code != 0:
        return ""
    return output


def request_instance():
    try:
        request = urllib.request.Request(
            f"{BASE_URL}/instance",
            headers={"Cache-Control": "no-cache"},
        )

        start = time.monotonic()

        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            elapsed = time.monotonic() - start
            body = json.loads(response.read().decode())

        return response.status, body.get("instance_id", ""), elapsed

    except urllib.error.HTTPError as exc:
        return exc.code, "", 0

    except Exception:
        return 0, "", 0


def send_traffic(count):
    results = []

    print(f"Sending {count} requests...")

    for number in range(1, count + 1):
        status, instance, elapsed = request_instance()

        if status == 200:
            results.append(instance)
            print(
                f"  {number:02d}: HTTP {status} "
                f"instance={instance} "
                f"time={elapsed:.3f}s"
            )
        else:
            results.append(f"ERROR:{status}")
            print(f"  {number:02d}: ERROR HTTP {status}")

    return results


def summarize(results):
    successful = [item for item in results if not item.startswith("ERROR:")]
    errors = [item for item in results if item.startswith("ERROR:")]

    counts = {}

    for instance in successful:
        counts[instance] = counts.get(instance, 0) + 1

    print(f"  Successful: {len(successful)}/{len(results)}")
    print(f"  Errors:     {len(errors)}/{len(results)}")
    print(f"  Instances:  {counts}")

    return len(successful), len(errors), counts


def wait_for_healthy(container):
    print(f"Waiting for {container} to become healthy...")

    deadline = time.monotonic() + HEALTH_WAIT

    while time.monotonic() < deadline:
        if docker_state(container) == "running" and docker_health(container) == "healthy":
            print(f"PASS: {container} is healthy again")
            return True

        time.sleep(2)

    print(f"FAIL: {container} did not become healthy within {HEALTH_WAIT}s")
    return False


def main():
    print("=== BARQ Backend Failure/Recovery Test ===")
    print(f"Base URL: {BASE_URL}")
    print()

    # ------------------------------------------------------------
    # 1. Confirm both backends are healthy before the test.
    # ------------------------------------------------------------

    print("--- Initial state ---")

    for container in ("app-01", "app-02"):
        state = docker_state(container)
        health = docker_health(container)

        print(f"{container}: state={state}, health={health}")

        if state != "running" or health != "healthy":
            print(f"FAIL: {container} is not healthy before the test")
            return 1

    # ------------------------------------------------------------
    # 2. Establish baseline traffic.
    # ------------------------------------------------------------

    print()
    print("--- Baseline traffic ---")

    baseline = send_traffic(REQUEST_COUNT)
    baseline_success, baseline_errors, baseline_instances = summarize(baseline)

    if baseline_success == 0:
        print("FAIL: no successful baseline requests")
        return 1

    if "app-01" not in baseline_instances or "app-02" not in baseline_instances:
        print("WARNING: baseline traffic did not reach both instances")

    # ------------------------------------------------------------
    # 3. Stop app-01.
    # ------------------------------------------------------------

    print()
    print("--- Simulating app-01 failure ---")

    code, output, error = run_command(
        ["docker", "stop", "app-01"]
    )

    if code != 0:
        print("FAIL: could not stop app-01")
        if error:
            print(error)
        return 1

    print("PASS: app-01 stopped")

    try:
        # Give Docker/NGINX a moment to notice the failure.
        time.sleep(3)

        # --------------------------------------------------------
        # 4. Send traffic while app-01 is down.
        # --------------------------------------------------------

        print()
        print("--- Traffic while app-01 is stopped ---")

        failed_backend = send_traffic(REQUEST_COUNT)
        success_count, error_count, instances = summarize(failed_backend)

        # We require the surviving backend to serve traffic.
        if success_count == 0:
            print("FAIL: no traffic succeeded while app-01 was down")
            return 1

        if "app-02" not in instances:
            print("FAIL: app-02 did not serve traffic while app-01 was down")
            return 1

        print("PASS: service remained available through app-02")

        # --------------------------------------------------------
        # 5. Restore app-01.
        # --------------------------------------------------------

        print()
        print("--- Restoring app-01 ---")

        code, output, error = run_command(
            ["docker", "start", "app-01"]
        )

        if code != 0:
            print("FAIL: could not start app-01")
            if error:
                print(error)
            return 1

        print("PASS: app-01 start requested")

        if not wait_for_healthy("app-01"):
            return 1

        # --------------------------------------------------------
        # 6. Prove traffic returns to both instances.
        # --------------------------------------------------------

        print()
        print("--- Traffic after recovery ---")

        recovered = send_traffic(REQUEST_COUNT)
        recovery_success, recovery_errors, recovery_instances = summarize(
            recovered
        )

        if recovery_success == 0:
            print("FAIL: no successful requests after recovery")
            return 1

        if "app-01" not in recovery_instances:
            print("FAIL: app-01 did not receive traffic after recovery")
            return 1

        if "app-02" not in recovery_instances:
            print("FAIL: app-02 did not receive traffic after recovery")
            return 1

        print("PASS: both application instances received traffic after recovery")

    finally:
        # --------------------------------------------------------
        # 7. Cleanup: make sure app-01 is running.
        # --------------------------------------------------------

        if docker_state("app-01") != "running":
            print()
            print("Cleanup: starting app-01")
            run_command(["docker", "start", "app-01"])

        if docker_state("app-01") == "running":
            wait_for_healthy("app-01")

    print()
    print("=== FAILURE/RECOVERY TEST PASSED ===")
    print()
    print("Evidence summary:")
    print(f"  Baseline successful requests: {baseline_success}/{REQUEST_COUNT}")
    print(f"  Requests during failure:      {success_count}/{REQUEST_COUNT}")
    print(f"  Errors during failure:       {error_count}/{REQUEST_COUNT}")
    print(f"  Requests after recovery:      {recovery_success}/{REQUEST_COUNT}")
    print(f"  Recovered instances:          {sorted(recovery_instances)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

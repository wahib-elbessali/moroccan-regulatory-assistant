"""P6 network isolation tests (spec section 8: T1, T2, T3).

They run against the live compose (`make test-isolation`). When the compose is
not up (for example in CI), every test is skipped.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PY_PROBE = [
    "python",
    "-c",
    "import socket; s=socket.create_connection(('1.1.1.1',443),timeout=5); "
    "print('connected'); s.close()",
]
BASH_PROBE = [
    "bash",
    "-c",
    "timeout 5 bash -c '</dev/tcp/1.1.1.1/443' && echo connected",
]
USES_PYTHON = {"api", "ocr", "searxng", "web-search"}

# What a genuinely blocked connection looks like (not a missing command).
NETWORK_ERROR = re.compile(r"unreachable|timed out|timeout", re.IGNORECASE)


def _running_services() -> set[str]:
    if shutil.which("docker") is None:
        return set()
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(result.stdout.split()) if result.returncode == 0 else set()


RUNNING = _running_services()

pytestmark = pytest.mark.skipif(
    not RUNNING, reason="docker compose is not running (use `make up` first)"
)


def _exec(service: str, cmd: list[str], timeout: int = 40):
    if service not in RUNNING:
        pytest.skip(f"service {service} is not running")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *cmd],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def _probe(service: str):
    cmd = PY_PROBE if service in USES_PYTHON else BASH_PROBE
    return _exec(service, cmd)


def _assert_blocked(service: str) -> None:
    code, out = _probe(service)
    assert "connected" not in out, f"{service} reached the internet:\n{out}"
    # exit code 124 = the `timeout` command killed a silent connection attempt
    genuine = code == 124 or NETWORK_ERROR.search(out)
    assert genuine, f"{service}: inconclusive (not a network error):\n{out}"


@pytest.mark.parametrize("service", ["searxng", "web-search"])
def test_control_egress_services_reach_internet(service):
    """Positive control: services allowed on `egress` must be able to go out."""
    _, out = _probe(service)
    assert "connected" in out, f"{service} cannot reach the internet:\n{out}"


def test_t1_api_cannot_reach_internet_directly():
    _assert_blocked("api")


def test_t1_api_cannot_fetch_example_com():
    code, out = _exec(
        "api",
        [
            "python",
            "-c",
            "import urllib.request as u; "
            "print(u.urlopen('https://example.com', timeout=10).status)",
        ],
    )
    assert code != 0 and "200" not in out, f"api fetched example.com:\n{out}"


def test_t2_web_search_reaches_searxng():
    code, out = _exec(
        "web-search",
        [
            "python",
            "-c",
            "import urllib.request as u; "
            "print(u.urlopen('http://searxng:8080/search?q=test&format=json', "
            "timeout=60).status)",
        ],
        timeout=90,
    )
    assert code == 0 and "200" in out, f"web-search cannot reach searxng:\n{out}"


@pytest.mark.parametrize(
    "service",
    [
        "llm",
        "models",
        "ocr",
        "postgres",
        "qdrant",
        "ui",
    ],
)
def test_t3_internal_services_cannot_reach_internet(service):
    _assert_blocked(service)

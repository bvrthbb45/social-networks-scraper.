"""Guards the deployment's security properties, so a later edit cannot quietly weaken them."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
services = compose["services"]
nginx = (ROOT / "deploy/proxy/nginx.conf").read_text()
api_proxy = (ROOT / "deploy/proxy/api_proxy.conf").read_text()
headers = (ROOT / "deploy/proxy/security_headers.conf").read_text()


def test_only_the_proxy_publishes_ports():
    assert [n for n, s in services.items() if s.get("ports")] == ["proxy"]


def test_database_is_on_an_internal_network_only():
    assert services["db"]["networks"] == ["data"]
    assert compose["networks"]["data"]["internal"] is True
    assert "ports" not in services["db"]


@pytest.mark.parametrize("name", ["api", "daily", "proxy"])
def test_runtime_containers_are_locked_down(name):
    s = services[name]
    assert s["read_only"] is True
    assert "no-new-privileges:true" in s["security_opt"]
    assert s["cap_drop"] == ["ALL"]


def test_application_services_inherit_the_hardening():
    for name in ("migrate", "api", "daily"):
        assert services[name]["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in services[name]["security_opt"]


def test_daily_job_and_api_share_the_media_volume_but_the_daily_job_has_no_edge_access():
    assert "media:/data/media" in services["api"]["volumes"]
    assert "media:/data/media" in services["daily"]["volumes"]
    assert services["daily"]["networks"] == ["data"]


def test_forwarded_headers_are_trusted_only_from_the_edge_network():
    subnet = compose["networks"]["edge"]["ipam"]["config"][0]["subnet"]
    assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] == subnet


def test_proxy_overwrites_forwarding_headers():
    assert "X-Forwarded-For $remote_addr;" in api_proxy
    assert "$proxy_add_x_forwarded_for" not in api_proxy


def test_proxy_terminates_tls_only_with_modern_protocols_and_hsts():
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx
    assert re.search(r"Strict-Transport-Security.*always", headers)
    assert "return 301 https://" in nginx


def test_proxy_limits_logins_and_hides_details():
    assert "zone=login" in nginx and "= /api/auth/login" in nginx
    assert "server_tokens off;" in nginx
    assert "access_log off;" in nginx


def test_csp_forbids_remote_content_and_framing():
    csp = re.search(r'Content-Security-Policy "([^"]+)"', headers).group(1)
    assert csp.startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in csp
    for directive in csp.split(";"):
        assert (
            "http:" not in directive
            and "https:" not in directive
            and "*" not in directive
        )


def test_secrets_never_live_in_the_compose_file():
    text = (ROOT / "docker-compose.yml").read_text()
    assert not re.search(r"(KEY|SECRET)\s*[:=]\s*\S{16,}", text)


def test_example_env_has_no_real_secret_values():
    example = (ROOT / ".env.example").read_text()
    for name in ("FIELD_ENCRYPTION_KEY", "BLIND_INDEX_KEY", "JWT_SECRET"):
        assert re.search(rf"^{name}=$", example, re.M)


def test_every_location_that_sets_a_header_also_includes_the_security_headers():
    # nginx discards inherited add_header directives once a location defines its own.
    for block in re.findall(r"location [^{]+\{(.*?)\n    \}", nginx, re.S):
        if "add_header" in block:
            assert "include /etc/nginx/security_headers.conf;" in block


def test_security_headers_snippet_is_complete_and_shipped():
    snippet = (ROOT / "deploy/proxy/security_headers.conf").read_text()
    for header in (
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
    ):
        assert header in snippet
    assert "security_headers.conf" in (ROOT / "deploy/proxy/Dockerfile").read_text()
    assert (
        "add_header" not in nginx.split("server {", 2)[2].split("location")[0]
    )  # only via the include

"""Validate the single Unraid/local Compose using isolated data and credentials.

By default use an archive of the working tree. --published downloads the pinned
release from GitHub. Neither mode starts a real Cloudflare tunnel.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--published", action="store_true", help="Download the pinned GitHub release"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compose_file = root / "docker-compose.unraid.yml"
    project = f"loyalty-deploy-check-{os.getpid()}"
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    files = sorted({name for name in files if name and (root / name).is_file()})
    assert not any(name == ".env" or name.startswith("data/") for name in files)
    digest = hashlib.sha1()
    for name in files:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    ref = digest.hexdigest()
    with tempfile.TemporaryDirectory(prefix="loyalty-deploy-check-") as temporary:
        folder = Path(temporary).resolve()
        assert folder.parent == Path(tempfile.gettempdir()).resolve()
        fixture = folder / "fixture"
        fixture.mkdir()
        with tarfile.open(fixture / "source.tar.gz", "w:gz") as archive:
            for name in files:
                archive.add(root / name, arcname=f"loyalty-{ref}/{name}")
        (folder / "data" / "certs").mkdir(parents=True)
        override = folder / "fixture.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "fixture": {
                            "image": "python:3.12-slim",
                            "working_dir": "/fixture",
                            "volumes": [f"{fixture.as_posix()}:/fixture:ro"],
                            "command": ["python", "-m", "http.server", "8000"],
                        },
                        "source": {
                            "depends_on": {"fixture": {"condition": "service_started"}}
                        },
                    }
                }
            )
        )
        if args.published:
            match = re.search(
                r"SOURCE_REF:-([0-9a-f]{40})", compose_file.read_text(encoding="utf-8")
            )
            assert match, "Compose must pin a complete release SHA"
            ref = match[1]
        api_port, admin_port = free_port(), free_port()
        while admin_port == api_port:
            admin_port = free_port()
        environment = {
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith("COMPOSE_")
            },
            "SOURCE_REF": ref,
            "SOURCE_URL": "" if args.published else "http://fixture:8000/source.tar.gz",
            "GITHUB_TOKEN": "",
            "DATA_DIR": (folder / "data").as_posix(),
            "CERTS_DIR": (folder / "data" / "certs").as_posix(),
            "API_PORT": str(api_port),
            "ADMIN_PORT": str(admin_port),
            "BOOTSTRAP_ADMIN_USERNAME": "deployment-check",
            "BOOTSTRAP_ADMIN_PASSWORD": "synthetic-deployment-password",
            "PAN_HASH_SECRET": "synthetic-deployment-secret",
            "GOOGLE_ISSUER_ID": "",
            "APPLE_TEAM_ID": "",
            "APPLE_CERT_PASSWORD": "",
            "AUTH_ENABLED": "false",
            "CLOUDFLARE_TUNNEL_TOKEN": "",
            "PUBLIC_API_URL": "https://api.example.com",
            "PUBLIC_ADMIN_URL": "https://admin.example.com",
        }
        empty_env = folder / "empty.env"
        empty_env.write_text("")
        command = [
            "docker",
            "compose",
            "--env-file",
            str(empty_env),
            "-p",
            project,
            "-f",
            str(compose_file),
        ]
        if not args.published:
            command += ["-f", str(override)]
        resolved = json.loads(
            subprocess.check_output(
                command + ["config", "--format", "json"],
                env=environment,
                cwd=root,
            )
        )
        tunnel = resolved["services"]["cloudflared"]
        assert not tunnel.get("profiles"), "Unraid must start Cloudflare by default"
        assert tunnel["image"] == "cloudflare/cloudflared:latest"
        assert tunnel["command"][-1] == "run"
        assert all(
            tunnel["depends_on"][service]["condition"] == "service_healthy"
            for service in ("api", "admin-web")
        )
        assert tunnel["environment"]["TUNNEL_TOKEN"] == ""
        for service in ("source", "web-build", "api", "admin-web"):
            assert resolved["services"][service]["environment"]["SOURCE_REF"] == ref
        print(
            "Single Compose: Cloudflare enabled by default; testing application at "
            + ref,
            flush=True,
        )
        try:
            subprocess.run(
                command
                + ["up", "-d", "--wait", "--wait-timeout", "600", "api", "admin-web"],
                env=environment,
                cwd=root,
                check=True,
            )
            base = f"http://127.0.0.1:{admin_port}"
            for route in ["/health", "/passes", "/campaigns", "/notifications", "/docs", "/redoc"]:
                with urllib.request.urlopen(base + route, timeout=15) as response:
                    assert response.status == 200
            with urllib.request.urlopen(base + "/openapi.json", timeout=15) as response:
                assert (
                    "delete"
                    in json.load(response)["paths"]["/api/v1/merchants/{merchant_id}"]
                )
            payload = json.dumps(
                {
                    "username": "deployment-check",
                    "password": "synthetic-deployment-password",
                }
            ).encode()
            request = urllib.request.Request(
                base + "/api/v1/auth/login",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                login = json.load(response)
                assert login["user"]["public_access"] is False
                token = login["access_token"]
                assert token
            # Admin sessions stay protected while business requests need no token.
            try:
                urllib.request.urlopen(base + "/api/v1/users/me", timeout=15)
                raise AssertionError("Anonymous admin identity must be rejected")
            except urllib.error.HTTPError as error:
                assert error.code == 401
            with urllib.request.urlopen(
                urllib.request.Request(
                    base + "/api/v1/users/me",
                    headers={"Authorization": "Bearer " + token},
                ),
                timeout=15,
            ) as response:
                assert json.load(response)["username"] == "deployment-check"

            def api_call(path, body=None):
                request = urllib.request.Request(
                    base + "/api/v1" + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    return json.load(response)

            merchant = api_call("/merchants", {"name": "Deployment fixture"})
            image = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAACAAAAAUCAIAAABj86gYAAAALElEQVR4nGP8z0BbwERj8xlGLSAIRoOIIBgNIoJgNIgIgtEgIghGg4iBEAAAKwkBJ9coQEsAAAAASUVORK5CYII="
            )
            assets = []
            for _ in range(2):
                request = urllib.request.Request(
                    base + f"/api/v1/merchants/{merchant['id']}/pass-assets",
                    data=image,
                    headers={
                        "Content-Type": "image/png",
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    assets.append(json.load(response)["id"])
            campaign = api_call(
                f"/merchants/{merchant['id']}/campaigns",
                {
                    "name": "Persistent rewards",
                    "type": "points_per_spend",
                    "config": {},
                    "design": {
                        "logo_asset_id": assets[0],
                        "hero_asset_id": assets[1],
                        "background_color": "#123456",
                    },
                },
            )
            customer = api_call(
                f"/merchants/{merchant['id']}/customers",
                {
                    "customer_code": "DEPLOY-1",
                    "name": "Synthetic customer",
                    "campaign_ids": [campaign["id"]],
                },
            )
            payment = api_call(
                "/transactions",
                {
                    "merchant_id": merchant["id"],
                    "external_transaction_id": "deployment-payment",
                    "amount": 20,
                    "identifiers": {"customer_number": "DEPLOY-1"},
                    "send_notification": True,
                    "notification": {
                        "title": "Purchase registered",
                        "message": "Amount {{amount}}, points {{currentPoints}}",
                    },
                },
            )
            assert payment["points_delta"] == 2
            notification_id = payment["notification_id"]
            assert notification_id and payment["notification_status"] == "skipped"
            notification_base = f"/merchants/{merchant['id']}/notifications"
            history = api_call(notification_base)
            assert history["total"] == 1
            assert history["items"][0]["reason"] == "no_passes"
            preview = api_call(
                notification_base + "/preview",
                {"target_type": "campaign", "campaign_id": campaign["id"],
                 "title": "Rewards", "message": "Your balance: {{currentPoints}}"},
            )
            assert preview["estimated_recipients"] == 0
            assert "no_passes" in preview["warnings"]
            subprocess.run(
                command + ["restart", "api"], env=environment, cwd=root, check=True
            )
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(
                        base + "/health", timeout=3
                    ) as response:
                        assert response.status == 200
                    break
                except (OSError, AssertionError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.5)
            saved = api_call(f"/campaigns/{campaign['id']}")
            assert saved["design"]["background_color"] == "#123456"
            notification = api_call(notification_base + "/" + notification_id)
            assert notification["status"] == "skipped"
            assert notification["sender_name"] == "public-test"
            assert notification["title"] == "Purchase registered"
            assert (
                api_call(f"/customers/{customer['customer']['id']}/campaigns")[0][
                    "points_balance"
                ]
                == 2
            )
            with urllib.request.urlopen(
                base + "/api/v1/public/pass-assets/" + assets[0], timeout=15
            ) as response:
                assert response.read().startswith(b"\x89PNG")
            request = urllib.request.Request(
                base + "/api/v1/auth/logout",
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                assert response.status == 200
            print(
                "Single Compose passed: source, dependency install, web build, health, authentication, design/image uploads, enrollment, payment, notification preview/audit and persistence after API restart. Cloudflare is configured for default startup; real tunnel connection is checked on Unraid."
            )
        finally:
            # Only the unique test project and its named volumes are removed.
            subprocess.run(
                command + ["down", "-v"], env=environment, cwd=root, check=False
            )


if __name__ == "__main__":
    main()

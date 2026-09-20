"""Exercise the standalone Compose with an unpublished local source archive.

Uses only synthetic credentials and isolated Docker resources. Production downloads
the same archive format from GitHub; this fixture does not publish local changes.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
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
        api_port, admin_port = free_port(), free_port()
        environment = {
            **os.environ,
            "SOURCE_REF": ref,
            "SOURCE_URL": "http://fixture:8000/source.tar.gz",
            "DATA_DIR": (folder / "data").as_posix(),
            "CERTS_DIR": (folder / "data" / "certs").as_posix(),
            "API_PORT": str(api_port),
            "ADMIN_PORT": str(admin_port),
            "BOOTSTRAP_ADMIN_USERNAME": "deployment-check",
            "BOOTSTRAP_ADMIN_PASSWORD": "synthetic-deployment-password",
            "PAN_HASH_SECRET": "synthetic-deployment-secret",
            "GOOGLE_ISSUER_ID": "",
            "CLOUDFLARE_TUNNEL_TOKEN": "",
            "PUBLIC_API_URL": "https://api.example.com",
            "PUBLIC_ADMIN_URL": "https://admin.example.com",
        }
        compose_file = root / "docker-compose.deploy.yml"
        if "--inline" in sys.argv:
            from render_install_compose import render

            content = render(root)
            assert content == (root / "docker-compose.install.yml").read_text(
                encoding="utf-8"
            )
            replacements = {
                "source_ref": ref,
                "source_url": environment["SOURCE_URL"],
                "admin_user": environment["BOOTSTRAP_ADMIN_USERNAME"],
                "admin_password": environment["BOOTSTRAP_ADMIN_PASSWORD"],
                "pan_secret": environment["PAN_HASH_SECRET"],
                "data_mount": environment["DATA_DIR"] + ":/data",
                "certs_mount": environment["CERTS_DIR"] + ":/certs:ro",
                "api_port": f"127.0.0.1:{api_port}:8000",
                "admin_port": f"127.0.0.1:{admin_port}:80",
            }
            import re

            for anchor, value in replacements.items():
                content = re.sub(
                    r"&" + anchor + r' "[^"\n]*"',
                    lambda match, anchor=anchor, value=value: (
                        "&" + anchor + " " + json.dumps(value)
                    ),
                    content,
                )
            compose_file = folder / "compose.yml"
            compose_file.write_text(content, encoding="utf-8")
        command = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            str(compose_file),
            "-f",
            str(override),
        ]
        try:
            subprocess.run(
                command + ["up", "-d", "--wait", "--wait-timeout", "600"],
                env=environment,
                cwd=root,
                check=True,
            )
            base = f"http://127.0.0.1:{admin_port}"
            for route in ["/health", "/passes", "/campaigns", "/docs", "/redoc"]:
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
                token = json.load(response)["access_token"]
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
                "Standalone Compose passed: source archive, dependency install, web build, health, SPA routes and authentication."
            )
        finally:
            # Only the unique test project and its named volumes are removed.
            subprocess.run(
                command + ["down", "-v"], env=environment, cwd=root, check=False
            )


if __name__ == "__main__":
    main()

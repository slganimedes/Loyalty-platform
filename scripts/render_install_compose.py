"""Regenerate the editable, no-.env installer from the canonical deployment file."""

import argparse
import re
from pathlib import Path


def render(root: Path) -> str:
    template = (root / "docker-compose.deploy.yml").read_text(encoding="utf-8")
    settings = {
        "SOURCE_REF": ("source_ref", "REPLACE_WITH_PUBLISHED_COMMIT"),
        "SOURCE_URL": ("source_url", ""),
        "GITHUB_TOKEN": ("github_token", ""),
        "PAN_HASH_SECRET": ("pan_secret", "REPLACE_WITH_STABLE_RANDOM_SECRET"),
        "BOOTSTRAP_ADMIN_USERNAME": ("admin_user", "admin"),
        "BOOTSTRAP_ADMIN_PASSWORD": ("admin_password", "REPLACE_WITH_RANDOM_PASSWORD"),
        "PUBLIC_API_URL": ("api_url", "https://api.slmartinez.org"),
        "PUBLIC_ADMIN_URL": ("admin_url", "https://admin.slmartinez.org"),
        "GOOGLE_ISSUER_ID": ("google_issuer", ""),
        "APPLE_TEAM_ID": ("apple_team", ""),
        "APPLE_PASS_TYPE_ID": ("apple_pass_type", "pass.org.slmartinez.loyalty"),
        "APPLE_CERT_PASSWORD": ("apple_password", ""),
        "APPLE_WEBSERVICE_URL": ("apple_url", "https://api.slmartinez.org"),
        "SESSION_HOURS": ("session_hours", "12"),
        "AUTH_ENABLED": ("auth_enabled", "false"),
        "PASS_ASSET_MAX_BYTES": ("asset_max_bytes", "4194304"),
        "PASS_ASSET_MAX_PIXELS": ("asset_max_pixels", "16777216"),
        "CLOUDFLARE_TUNNEL_TOKEN": ("tunnel_token", ""),
    }
    import json

    header = "# Copy to docker-compose.private.yml before filling in credentials.\n"
    header += "# Edit only x-installation. No .env required. Do not commit the private copy.\n"
    header += (
        "# For a literal dollar sign in a value, enter $$ (Docker Compose escaping).\n"
    )
    header += "x-installation:\n"
    for name, (anchor, default) in settings.items():
        header += f"  {name}: &{anchor} {json.dumps(default)}\n"
    header += '  DATA_MOUNT: &data_mount "./data:/data"\n'
    header += '  CERTS_MOUNT: &certs_mount "./data/certs:/certs:ro"\n'
    header += '  API_PORT: &api_port "127.0.0.1:8000:8000"\n'
    header += '  ADMIN_PORT: &admin_port "127.0.0.1:8080:80"\n\n'
    lines = []
    for line in template[template.index("services:") :].splitlines():
        if "${" in line:
            key = line.strip().split(":", 1)[0]
            indent = line[: len(line) - len(line.lstrip())]
            if key in settings:
                line = indent + key + ": *" + settings[key][0]
            elif key == "TUNNEL_TOKEN":
                line = indent + "TUNNEL_TOKEN: *tunnel_token"
            elif "${DATA_DIR" in line:
                line = indent + "- *data_mount"
            elif "${CERTS_DIR" in line:
                line = indent + "- *certs_mount"
            elif "${API_PORT" in line:
                line = indent + "ports: [*api_port]"
            elif "${ADMIN_PORT" in line:
                line = indent + "ports: [*admin_port]"
            else:
                raise ValueError("Unknown deployment setting: " + line)
        lines.append(line)
    return header + "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unraid-ref", help="Pin the Unraid template to an existing source commit"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    (root / "docker-compose.install.yml").write_text(render(root), encoding="utf-8")
    if args.unraid_ref:
        if not re.fullmatch(r"[0-9a-f]{40}", args.unraid_ref):
            parser.error("--unraid-ref must be a full commit SHA")
        content = render(root).replace("REPLACE_WITH_PUBLISHED_COMMIT", args.unraid_ref)
        content = content.replace(
            '"./data:/data"', '"/mnt/user/appdata/loyalty-platform/data:/data"'
        )
        content = content.replace(
            '"./data/certs:/certs:ro"',
            '"/mnt/user/appdata/loyalty-platform/data/certs:/certs:ro"',
        )
        # The tunnel is the entry point; avoid collisions with Unraid's existing ports.
        content = (
            "\n".join(
                line
                for line in content.splitlines()
                if not any(
                    part in line
                    for part in [
                        "profiles: [tunnel]",
                        "ports: [*",
                        "API_PORT: &",
                        "ADMIN_PORT: &",
                    ]
                )
            )
            + "\n"
        )
        content = (
            "# Unraid: paste this entire file in Compose File. Tunnel starts automatically.\n"
            + content
        )
        (root / "docker-compose.unraid.yml").write_text(content, encoding="utf-8")

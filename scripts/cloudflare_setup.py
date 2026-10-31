#!/usr/bin/env python3
"""Prepare a named Cloudflare Tunnel without launching it or changing DNS."""

import getpass
import ipaddress
import os
import re
import tempfile
from pathlib import Path


def hostname(value):
    value = value.strip().lower()
    if value.startswith("https://"):
        value = value[8:].rstrip("/")
    labels = value.split(".")
    if (
        len(value) > 253
        or len(labels) < 2
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("Usa un dominio como social.tudominio.cl, sin puerto ni ruta.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("Usa un dominio, no una dirección IP.")
    if labels[-1] in {"localhost", "local", "internal", "test", "invalid"}:
        raise ValueError("Usa un dominio público que administres en Cloudflare.")
    return value


def update_env(text, values):
    """Replace only owned keys; preserve all unrelated credentials and comments."""
    remaining = dict(values)
    lines = []
    for line in text.splitlines():
        key = line.partition("=")[0].strip()
        if key in values:
            if key in remaining:
                lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


def atomic_private(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".avia-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(root, domain, token):
    domain = hostname(domain)
    token = token.strip()
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{40,4096}", token):
        raise ValueError("Pega solo el token del túnel, no el comando Docker completo.")
    env_path = root / ".env"
    original = env_path.read_text()
    current = dict(line.split("=", 1) for line in original.splitlines() if "=" in line and not line.startswith("#"))
    profiles = current.get("COMPOSE_PROFILES", "").strip("\"'").split(",")
    profiles = [p.strip() for p in profiles if p.strip() and p.strip() != "cloudflare"] + ["cloudflare"]
    values = {
        "APP_URL": f"https://{domain}",
        "ALLOWED_HOSTS": f"{domain},localhost,127.0.0.1,app",
        "AVIA_HTTPS": "true",
        "COMPOSE_PROFILES": ",".join(profiles),
        "AVIA_TUNNEL_UID": str(os.getuid()),
        "AVIA_TUNNEL_GID": str(os.getgid()),
    }
    directory = root / ".cloudflare"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    # Keep the first pre-tunnel configuration for explicit recovery; never overwrite it.
    backup = directory / "env.before-tunnel"
    if not backup.exists():
        atomic_private(backup, original)
    atomic_private(directory / "tunnel.token", token)
    atomic_private(env_path, update_env(original, values))
    return domain


def main():
    root = Path(__file__).resolve().parents[1]
    print("Cloudflare → Networks → Tunnels: crea un túnel Cloudflared y elige Docker.")
    print("Publica tu hostname con servicio HTTP, URL app:8000. No uses localhost.")
    print("Esto prepara archivos locales; no crea DNS ni inicia contenedores.")
    try:
        domain = hostname(input("Dominio público (social.tudominio.cl): "))
        token = getpass.getpass("Token del túnel (oculto): ")
        domain = configure(root, domain, token)
    except (ValueError, OSError) as error:
        raise SystemExit(f"No se pudo preparar: {error}") from None
    print(f"Preparado: https://{domain}")
    print("Activa en Cloudflare Always Use HTTPS para este hostname.")
    print("Aplica: docker compose up -d --build --wait app worker cloudflared")
    print("Abre el dominio, inicia sesión y copia los callbacks del onboarding a Meta/Google.")
    print("Guía y recuperación: docs/CLOUDFLARE.md. Las cuentas y claves existentes se conservan.")


if __name__ == "__main__":
    main()

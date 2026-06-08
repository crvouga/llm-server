"""Ensure host dependencies are present: Docker (+ NVIDIA runtime), cloudflared."""

import os
import platform
import shutil
import subprocess
import tempfile
import time

from .console import die, info, ok, section, warn
from .gpu import _gpu_test
from .shell import run


def _docker_reachable(argv):
    return (
        subprocess.run(
            [*argv, "info"],
            capture_output=True,
        ).returncode
        == 0
    )


def _docker_socket_permission_denied() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "info"], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in (r.stdout + r.stderr).lower()


def _ensure_nvidia_cdi():
    from pathlib import Path

    if (
        platform.system() != "Linux"
        or Path("/etc/cdi/nvidia.yaml").exists()
        or not shutil.which("nvidia-ctk")
        or not shutil.which("systemctl")
    ):
        return
    info("Generating NVIDIA CDI specs (fixes --gpus all on newer Docker)...")
    run(["sudo", "mkdir", "-p", "/etc/cdi"])
    run(["sudo", "nvidia-ctk", "cdi", "generate", "--output=/etc/cdi/nvidia.yaml"])
    run(["sudo", "systemctl", "restart", "docker"])
    time.sleep(2)


def _resolve_docker_cmd():
    for argv in (["docker"], ["sudo", "docker"]):
        if _docker_reachable(argv):
            return argv

    if shutil.which("docker") and shutil.which("systemctl"):
        if subprocess.run(
            ["systemctl", "is-active", "--quiet", "docker"],
            capture_output=True,
        ).returncode != 0:
            info("Docker daemon not running — starting...")
            start = subprocess.run(
                ["sudo", "systemctl", "start", "docker"],
                capture_output=True,
                text=True,
            )
            if start.returncode != 0:
                journal = subprocess.run(
                    ["journalctl", "-u", "docker.service", "-n", "30", "--no-pager"],
                    capture_output=True,
                    text=True,
                )
                if "invalid database" in journal.stdout:
                    info("BuildKit database corrupted — resetting...")
                    run(["sudo", "rm", "-rf", "/var/lib/docker/buildkit"])
                    run(["sudo", "systemctl", "reset-failed", "docker"])
                    run(["sudo", "systemctl", "start", "docker"])
                    time.sleep(2)
                    for argv in (["docker"], ["sudo", "docker"]):
                        if _docker_reachable(argv):
                            return argv
                die(
                    "Docker daemon failed to start. "
                    "Check: systemctl status docker.service"
                )
            time.sleep(2)
            for argv in (["docker"], ["sudo", "docker"]):
                if _docker_reachable(argv):
                    return argv

    if platform.system() == "Darwin":
        die(
            "Cannot connect to Docker. Start Docker Desktop and wait until "
            "`docker info` succeeds, then retry."
        )

    if (
        platform.system() == "Linux"
        and _docker_socket_permission_denied()
        and shutil.which("systemctl")
        and subprocess.run(
            ["systemctl", "is-active", "--quiet", "docker"],
            capture_output=True,
        ).returncode
        == 0
    ):
        user = os.environ.get("USER", "your-user")
        die(
            "Cannot access Docker (permission denied on /var/run/docker.sock). "
            "The daemon is running.\n\n"
            f"  sudo usermod -aG docker {user}\n"
            "  newgrp docker   # or log out and back in\n\n"
            "Then rerun: make server-start"
        )

    die(
        "Cannot connect to Docker. Ensure the daemon is running "
        "(sudo systemctl start docker) or add your user to the docker group."
    )


def _install_nvidia_container_toolkit():
    info("NVIDIA container toolkit not found — installing...")
    run(
        [
            "bash",
            "-c",
            "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey "
            "| sudo gpg --batch --yes --dearmor "
            "-o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg",
        ]
    )
    run(
        [
            "bash",
            "-c",
            "curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list "
            "| sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' "
            "| sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list",
        ]
    )
    run(["sudo", "apt-get", "update", "-qq"])
    run(["sudo", "apt-get", "install", "-y", "-q", "nvidia-container-toolkit"])


def ensure_docker(cfg):
    section("Checking Docker")

    if not shutil.which("docker"):
        info("Docker not found — installing...")
        run(["bash", "-c", "curl -fsSL https://get.docker.com | sudo sh"])
        run(["sudo", "usermod", "-aG", "docker", os.environ["USER"]])
        warn(
            f"Added {os.environ['USER']} to docker group — may need re-login on first install"
        )
    else:
        r = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        ok(r.stdout.strip())

    docker_cmd = _resolve_docker_cmd()
    _ensure_nvidia_cdi()

    if _gpu_test(docker_cmd):
        ok("NVIDIA container toolkit working")
        cfg.docker_cmd = docker_cmd
        return docker_cmd

    if shutil.which("nvidia-ctk"):
        info("NVIDIA container toolkit installed — configuring runtime...")
    else:
        _install_nvidia_container_toolkit()

    run(["sudo", "nvidia-ctk", "runtime", "configure", "--runtime=docker"])
    _ensure_nvidia_cdi()
    if shutil.which("systemctl"):
        run(["sudo", "systemctl", "restart", "docker"])
        time.sleep(2)
    docker_cmd = _resolve_docker_cmd()

    if not _gpu_test(docker_cmd):
        die(
            "Docker GPU access failed. "
            "Check NVIDIA drivers (nvidia-smi) and container toolkit."
        )

    ok("NVIDIA container toolkit working")
    cfg.docker_cmd = docker_cmd
    return docker_cmd


def ensure_cloudflared():
    section("Checking cloudflared")
    if shutil.which("cloudflared"):
        r = subprocess.run(["cloudflared", "--version"], capture_output=True, text=True)
        ok(r.stdout.strip())
        return

    if platform.system() == "Darwin":
        die(
            "cloudflared not found. Install with: brew install cloudflared\n"
            "  (This server is meant to run on the GB10 Spark host, not macOS.)"
        )

    arch = platform.machine()
    cf_arch = {"aarch64": "arm64", "x86_64": "amd64"}.get(arch)
    if not cf_arch:
        die(f"Unsupported arch for cloudflared: {arch}")

    info(f"cloudflared not found — installing for {arch}...")
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{cf_arch}.deb"
    tmp = tempfile.mktemp(suffix=".deb")
    run(["curl", "-fsSL", url, "-o", tmp])
    run(["sudo", "dpkg", "-i", tmp])
    os.unlink(tmp)
    ok("cloudflared installed")

"""
Full Cipher pipeline:
  1. Start Qdrant
  2. Chunk SRTs → chunks.json
  3. Embed new chunks into Qdrant
  4. Start FastAPI backend
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run(label: str, cmd: list[str]) -> None:
    print(f"\n▶ {label}...")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\n❌ Failed: {label}")
        sys.exit(result.returncode)


def start_docker() -> None:
    print("\n▶ Starting Docker...")
    result = subprocess.run(["docker", "info"], capture_output=True)
    if result.returncode == 0:
        print("  ✅ Docker already running")
        return
    subprocess.run(["open", "-a", "Docker"], check=True)
    print("  ⏳ Waiting for Docker to start...")
    for _ in range(30):
        time.sleep(2)
        if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
            print("  ✅ Docker ready")
            return
    print("  ❌ Docker did not start in time")
    sys.exit(1)


def start_qdrant() -> None:
    print("\n▶ Starting Qdrant...")
    running = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    ).stdout
    if "qdrant" in running.splitlines():
        print("  ✅ Qdrant already running")
        return

    # Try starting existing container first
    start = subprocess.run(["docker", "start", "qdrant"], capture_output=True)
    if start.returncode != 0:
        # Container doesn't exist — create it
        subprocess.run([
            "docker", "run", "-d",
            "-p", "6333:6333",
            "--name", "qdrant",
            "qdrant/qdrant",
        ], check=True)

    print("  ⏳ Waiting for Qdrant to be ready...")
    time.sleep(3)
    print("  ✅ Qdrant started")


def main() -> None:
    print()
    print("━" * 42)
    print("  Cipher Pipeline")
    print("━" * 42)

    start_docker()
    start_qdrant()

    run("Chunking SRTs → chunks.json",       [sys.executable, "scripts/chunk_srt.py"])
    run("Embedding into Qdrant",             [sys.executable, "scripts/embed.py"])

    print()
    print("━" * 42)
    print("  ✅ Pipeline complete — starting backend")
    print("━" * 42)
    print("  API → http://0.0.0.0:8000")
    print("  Press Ctrl+C to stop\n")

    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload",
    ], cwd=ROOT)


if __name__ == "__main__":
    main()

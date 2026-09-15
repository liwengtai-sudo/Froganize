"""Launch the frozen GUI bundle against disposable paths."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path


def smoke_test(bundle: Path, timeout: float = 20.0) -> None:
    executable = bundle / "Contents" / "MacOS" / "Froganize"
    if not executable.is_file():
        raise FileNotFoundError(f"Missing frozen executable: {executable}")

    with tempfile.TemporaryDirectory(prefix="froganize-bundle-smoke-") as raw_root:
        root = Path(raw_root)
        home = root / "Home"
        desktop = root / "Desktop"
        workspace = root / "Workspace"
        state = root / "State"
        ready = root / "gui-ready"
        home.mkdir()
        desktop.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "FROGANIZE_WORKSPACE": str(workspace),
                "FROGANIZE_DESKTOP": str(desktop),
                "FROGANIZE_STATE_DIR": str(state),
                "FROGANIZE_SMOKE_READY_FILE": str(ready),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        process = subprocess.Popen(
            [str(executable)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                return_code = process.poll()
                if ready.is_file():
                    if not (workspace / "Timeline").is_dir():
                        raise RuntimeError(
                            "The frozen app did not initialize its workspace."
                        )
                    if (state / "server.json").exists():
                        raise RuntimeError("The GUI app unexpectedly created web state.")
                    if return_code is None:
                        process.wait(timeout=5)
                    if process.returncode != 0:
                        stdout, stderr = process.communicate()
                        raise RuntimeError(
                            f"Frozen app exited with {process.returncode}.\n"
                            f"stdout: {stdout}\nstderr: {stderr}"
                        )
                    return
                if return_code is not None:
                    stdout, stderr = process.communicate()
                    raise RuntimeError(
                        f"Frozen app exited early ({process.returncode}).\n"
                        f"stdout: {stdout}\nstderr: {stderr}"
                    )
                time.sleep(0.1)
            raise TimeoutError("Timed out waiting for the frozen Froganize window.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    smoke_test(args.bundle.resolve())
    print("Frozen Froganize bundle smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CommandError(RuntimeError):
    pass


@dataclass
class Result:
    stdout: str
    stderr: str
    returncode: int


def run(
    argv: Sequence[str | Path],
    *,
    input_text: str | None = None,
    check: bool = True,
    capture: bool = True,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Result:
    args = [str(value) for value in argv]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=capture,
        env=merged_env,
        cwd=cwd,
        check=False,
    )
    result = Result(proc.stdout or "", proc.stderr or "", proc.returncode)
    if check and proc.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CommandError(f"command failed ({proc.returncode}): {args[0]}: {detail}")
    return result


def require(*commands: str) -> None:
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        raise CommandError("required command(s) missing: " + ", ".join(missing))


def log(component: str, message: str) -> None:
    print(f"[{component}] {message}")


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        temp = Path(f.name)
        if mode is not None:
            os.chmod(temp, mode)
        f.write(content)
    temp.replace(path)


def json_output(argv: Sequence[str | Path], **kwargs: Any) -> Any:
    return json.loads(run(argv, **kwargs).stdout)


def wait_until(predicate: Any, timeout: float, interval: float, description: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise CommandError(f"timed out waiting for {description}")
        time.sleep(interval)


def invoke_main(main_func: Any, argv: list[str]) -> int:
    previous = sys.argv
    try:
        sys.argv = [previous[0], *argv]
        value = main_func()
        return int(value or 0)
    finally:
        sys.argv = previous

from __future__ import annotations

import os
import sys


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else ""
    if "Username" in prompt:
        value = os.environ.get("FORGEJO_GIT_USERNAME")
    elif "Password" in prompt:
        value = os.environ.get("FORGEJO_GIT_PASSWORD")
    else:
        return 1
    if value is None:
        return 1
    print(value)
    return 0

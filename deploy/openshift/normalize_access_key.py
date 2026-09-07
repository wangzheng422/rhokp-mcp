#!/usr/bin/env python3
# AI-Author: Codex (OpenAI gpt-5.6-sol)
# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Normalize a mode-0600 RHoKP access-key handoff without printing it."""

import os
import stat
import sys


def normalize(source: str, destination: str) -> None:
    mode = stat.S_IMODE(os.stat(source).st_mode)
    if mode not in (0o400, 0o600):
        raise ValueError("credential file must have mode 0400 or 0600")
    with open(source, "rb") as stream:
        raw = stream.read()
    normalized = raw.rstrip(b"\r\n")
    if raw not in (normalized, normalized + b"\n", normalized + b"\r\n"):
        raise ValueError("RHoKP access-key file must contain exactly one value")
    if len(normalized) < 20 or any(chr(byte).isspace() for byte in normalized):
        raise ValueError("RHoKP access key is invalid")
    with open(destination, "wb") as stream:
        stream.write(normalized)
    os.chmod(destination, 0o600)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} SOURCE DESTINATION", file=sys.stderr)
        return 2
    try:
        normalize(sys.argv[1], sys.argv[2])
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print("access_key_normalization=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

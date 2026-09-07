#!/usr/bin/env python3
# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Validate a protected key and create a newline-free mode-0600 copy."""

import os
import stat
import sys


def normalize(source: str, destination: str) -> None:
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("access-key input must be a regular file")
        if stat.S_IMODE(metadata.st_mode) not in (0o400, 0o600):
            raise ValueError("access-key input must have mode 0400 or 0600")
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("access-key input is too large")
    normalized = raw.rstrip(b"\r\n")
    if raw not in (normalized, normalized + b"\n", normalized + b"\r\n"):
        raise ValueError("access-key input must contain exactly one value")
    if len(normalized) < 20 or any(byte < 33 or byte > 126 for byte in normalized):
        raise ValueError("access-key input must be a nonempty printable ASCII key without whitespace")
    # Never follow a destination symlink or overwrite an existing credential.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(normalized)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: normalize_access_key.py SOURCE NEW_DESTINATION", file=sys.stderr)
        return 2
    try:
        normalize(sys.argv[1], sys.argv[2])
    except (OSError, ValueError):
        print("Access-key normalization failed: check input permissions/format and use a new destination.", file=sys.stderr)
        return 2
    print("access_key_normalization=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

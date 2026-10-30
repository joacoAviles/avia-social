#!/usr/bin/env python3
"""Read the fixed private AVIA source via gh; store only in ignored runtime secrets/."""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REPOSITORY = "joacoAviles/avia-rockets-brand"


def read(path):
    return json.loads(
        subprocess.check_output(
            ["gh", "api", "--hostname", "github.com", "--method", "GET", "repos/" + REPOSITORY + path]
        )
    )


def main():
    commit = read("/commits/main")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("Invalid commit")
    file = read("/contents/brand/brand.yaml?ref=" + commit)
    raw = base64.b64decode(file["content"])
    if len(raw) > 65536 or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != file["sha"]:
        raise SystemExit("Invalid manifest integrity")
    envelope = {"repository": REPOSITORY, "commit": commit, "blob_sha": file["sha"], "manifest": raw.decode("utf-8")}
    directory = Path(__file__).resolve().parents[1] / "secrets"
    directory.mkdir(mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ui-brand-", dir=directory)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(envelope, output)
        os.replace(tmp, directory / "ui-brand.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("Private UI source imported at commit " + commit + ". No logo approved or published.")
    print("Ensure the read-only runtime mount is readable by container UID 10001; see docs/BRANDING.md.")


if __name__ == "__main__":
    main()

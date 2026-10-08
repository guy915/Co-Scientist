import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path


TOOLS = {
    "gitleaks": (
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    ),
    "actionlint": (
        "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz",
        "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
    ),
}


def extract_verified(
    archive: bytes, checksum: str, binary: str, destination: Path
) -> None:
    if hashlib.sha256(archive).hexdigest() != checksum:
        raise ValueError(f"{binary}: archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as contents:
        member = contents.getmember(binary)
        if not member.isfile():
            raise ValueError(f"{binary}: expected a regular file")
        source = contents.extractfile(member)
        if source is None:
            raise ValueError(f"{binary}: archive lacks executable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read())
        destination.chmod(0o755)


def install(binary: str, directory: Path) -> Path:
    url, checksum = TOOLS[binary]
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read()
    destination = directory / binary
    extract_verified(archive, checksum, binary, destination)
    print(f"Installed checksum-verified {binary} at {destination}")
    return destination


if __name__ == "__main__":
    install(sys.argv[1], Path(sys.argv[2]))

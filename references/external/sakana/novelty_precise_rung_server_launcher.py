"""Preflight and serve one pinned M11 PubMed MCP build in this process."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import ModuleType
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

SCHEMA_VERSION = "novelty_precise_rung_launcher_receipt_v1"
SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
TRACE_ENV = "COSCIENTIST_PUBMED_PILOT_TRACE"
BUILD_ENV = "COSCIENTIST_PUBMED_PILOT_BUILD_ID"
CACHE_ENV = "COSCIENTIST_LIT_REVIEW_DIR"
SERVER_MODULE = "mcp_server.server:app"
PROBE_IDS = ["99000001", "99000002", "99000003"]


class PreflightError(RuntimeError):
    """A launch prerequisite could not be proven offline."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_tree_sha256(root: Path) -> str:
    server_root = root / "engine" / "mcp_server"
    if not server_root.is_dir() or server_root.is_symlink():
        raise PreflightError("Pinned MCP source tree is missing or symlinked")
    digest = hashlib.sha256()
    for path in sorted(server_root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise PreflightError("Pinned MCP source tree contains a symlink")
        if path.is_file():
            digest.update(path.relative_to(server_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _check_environment(
    source_root: Path, cache_root: Path, tree_sha256: str
) -> tuple[str, int]:
    secret = os.environ.get(SECRET_ENV, "")
    if len(secret) < 32:
        raise PreflightError("A transient 32-character MCP shared secret is required")
    forbidden_suffixes = (
        "_API_KEY",
        "_ACCESS_KEY_ID",
        "_ACCESS_KEY",
        "_KEY",
        "_TOKEN",
        "_SECRET",
        "_PASSWORD",
        "_PRIVATE_KEY",
        "_CREDENTIALS",
    )
    extra = sorted(
        name
        for name, value in os.environ.items()
        if value
        and name != SECRET_ENV
        and (
            name.endswith(forbidden_suffixes)
            or name == "GOOGLE_APPLICATION_CREDENTIALS"
        )
    )
    if extra:
        raise PreflightError(f"Ambient credentials are set: {', '.join(extra)}")
    if os.getenv("DISABLE_SSL_VERIFY", "").lower() in {"1", "true", "yes"}:
        raise PreflightError("TLS verification must stay enabled")
    roots = {source_root, Path(__file__).resolve().parents[3]}
    if any(
        (root / relative).exists() or (root / relative).is_symlink()
        for root in roots
        for relative in (".env", "engine/.env", "engine/mcp_server/.env")
    ):
        raise PreflightError("Pinned source root contains a credential .env file")

    os.environ[CACHE_ENV] = str(cache_root)
    os.environ[TRACE_ENV] = "1"
    os.environ[BUILD_ENV] = tree_sha256
    expected = {
        CACHE_ENV: str(cache_root),
        TRACE_ENV: "1",
        BUILD_ENV: tree_sha256,
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise PreflightError(
            "Trace/cache/build environment did not match the pinned launch"
        )
    if os.environ.get(SECRET_ENV) != secret:
        raise PreflightError("MCP shared secret changed during environment setup")
    return secret, len(secret)


def _cache_root(path: Path) -> Path:
    if path.is_symlink():
        raise PreflightError("Cache root must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or any(resolved.iterdir()):
        raise PreflightError("Readiness cache must exist and be empty before launch")
    return resolved


def _require_outside(path: Path, roots: tuple[Path, ...], label: str) -> None:
    resolved = path.resolve()
    if any(
        resolved == root or root in resolved.parents or resolved in root.parents
        for root in roots
    ):
        raise PreflightError(f"{label} must not overlap a protected root")


def _set_entrez_retry_policy(entrez: ModuleType) -> None:
    entrez.max_tries = 1
    entrez.sleep_between_tries = 0
    if (entrez.max_tries, entrez.sleep_between_tries) != (1, 0):
        raise PreflightError("Biopython Entrez retry policy could not be set")


def _guard_network(stack: ExitStack) -> list[str]:
    blocked: list[str] = []
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            address = ipaddress.ip_address(str(host))
            loopback = address.is_loopback
        except ValueError:
            loopback = str(host).lower() in {"localhost", "ip6-localhost"}
        if not loopback:
            blocked.append("dns")
            raise PreflightError("Offline preflight attempted external name resolution")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) and address else ""
        try:
            loopback = ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            loopback = str(host).lower() in {"localhost", "ip6-localhost"}
        if not loopback:
            blocked.append("connect")
            raise PreflightError(
                "Offline preflight attempted an external socket connection"
            )
        return original_connect(sock, address)

    stack.enter_context(_patch_attr(socket, "getaddrinfo", guarded_getaddrinfo))
    stack.enter_context(_patch_attr(socket.socket, "connect", guarded_connect))
    return blocked


class _patch_attr:
    """Small stdlib-only attribute patch context manager with identity restore."""

    def __init__(self, target: Any, name: str, value: Any):
        self.target, self.name, self.value = target, name, value
        self.original = getattr(target, name)

    def __enter__(self) -> Any:
        setattr(self.target, self.name, self.value)
        return self.original

    def __exit__(self, *_: Any) -> None:
        setattr(self.target, self.name, self.original)


def _network_snapshot() -> tuple[Any, Any]:
    return socket.getaddrinfo, socket.socket.connect


def _network_restored(snapshot: tuple[Any, Any]) -> bool:
    current = _network_snapshot()
    return current[0] is snapshot[0] and current[1] is snapshot[1]


def _fake_entrez_handle(response: Any) -> Any:
    class Handle:
        def __init__(self, value: Any):
            self.response = value

        def close(self) -> None:
            return None

        def read(self) -> bytes:
            return self.response if isinstance(self.response, bytes) else b""

        def __contains__(self, _needle: object) -> bool:
            return False

    return Handle(response)


def _fake_article(pmid: str) -> dict[str, Any]:
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "DateRevised": {"Year": "2026", "Month": "1", "Day": "1"},
                    "Article": {
                        "ArticleTitle": f"Offline launcher probe {pmid}",
                        "Abstract": {"AbstractText": ["Offline test abstract."]},
                        "AuthorList": [],
                        "Journal": {"Title": "Offline test journal"},
                        "PublicationTypeList": [],
                    },
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }


def _remove_readiness_cache(cache_root: Path, slug: str) -> bool:
    pubmed_root = cache_root / "pubmed"
    probe_root = pubmed_root / slug
    if probe_root.is_symlink() or pubmed_root.is_symlink():
        raise PreflightError("Readiness cache unexpectedly contains a symlink")
    if probe_root.exists():
        shutil.rmtree(probe_root)
    try:
        pubmed_root.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return not any(cache_root.iterdir())


def _maintained_trace_probe(
    entrez: ModuleType,
    tool: ModuleType,
    pubmed_client: ModuleType,
    cache_root: Path,
    tree_sha256: str,
) -> dict[str, Any]:
    pid = os.getpid()
    run_id = slug = f"m11_launcher_probe_{pid}"
    run_root = cache_root / "pubmed" / slug / "runs" / run_id
    trace_path = run_root / ".search-trace.json"
    manifest_path = run_root / ".manifest.json"
    calls: dict[str, list[dict[str, Any]]] = {"esearch": [], "efetch": [], "elink": []}

    def fake_esearch(**kwargs: Any) -> Any:
        calls["esearch"].append(kwargs)
        return _fake_entrez_handle({"IdList": PROBE_IDS})

    def fake_efetch(**kwargs: Any) -> Any:
        calls["efetch"].append(kwargs)
        if kwargs.get("db") == "pmc":
            return _fake_entrez_handle(b"<article>offline launcher probe</article>")
        return _fake_entrez_handle(_fake_article(str(kwargs["id"])))

    def fake_elink(**kwargs: Any) -> Any:
        calls["elink"].append(kwargs)
        return _fake_entrez_handle(
            [{"LinkSetDb": [{"Link": [{"Id": f"PMC{kwargs['id']}"}]}]}]
        )

    source_path = Path(pubmed_client.__file__).resolve()
    original = {
        name: getattr(entrez, name) for name in ("esearch", "efetch", "elink", "read")
    }
    trace_digest = ""
    error: BaseException | None = None
    blocked: list[str] = []
    network_snapshot = _network_snapshot()
    patches_restored = False
    try:
        with ExitStack() as stack:
            blocked = _guard_network(stack)
            stack.enter_context(_patch_attr(entrez, "esearch", fake_esearch))
            stack.enter_context(_patch_attr(entrez, "efetch", fake_efetch))
            stack.enter_context(_patch_attr(entrez, "elink", fake_elink))
            stack.enter_context(
                _patch_attr(entrez, "read", lambda handle: handle.response)
            )
            result = asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="offline launcher trace probe",
                    slug=slug,
                    max_papers=3,
                    run_id=run_id,
                )
            )
        if blocked:
            raise PreflightError(
                "Offline trace probe attempted external network access"
            )
        if any(getattr(entrez, name) is not value for name, value in original.items()):
            raise PreflightError("Fake Entrez trace handlers were not restored")
        if not trace_path.is_file() or trace_path.is_symlink():
            raise PreflightError(
                "Maintained PubMed tool did not write its expected trace"
            )
        trace_bytes = trace_path.read_bytes()
        trace_digest = hashlib.sha256(trace_bytes).hexdigest()
        trace = json.loads(trace_bytes)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        esearch = calls["esearch"]
        fetched = trace.get("fetched", [])
        valid = (
            list(result) == PROBE_IDS
            and len(esearch) == 1
            and esearch[0].get("sort") == "pub_date"
            and trace.get("run_id") == run_id
            and trace.get("server_build_id") == tree_sha256
            and trace.get("process_id") == pid
            and trace.get("source_file") == str(source_path)
            and trace.get("sort") == "pub_date"
            and len(trace.get("attempts", [])) == 1
            and trace.get("attempts", [{}])[0].get("rung_type") == "exact"
            and trace.get("attempts", [{}])[0].get("first_ids") == PROBE_IDS
            and trace.get("selected", {}).get("ids") == PROBE_IDS
            and trace.get("final_ids") == list(result)
            and manifest.get("run_id") == run_id
            and manifest.get("paper_ids") == PROBE_IDS
            and manifest.get("query") == "offline launcher trace probe"
            and [item.get("pmid") for item in fetched] == PROBE_IDS
            and all(
                item.get("fetched") and item.get("pmc_available") for item in fetched
            )
            and len([call for call in calls["efetch"] if call.get("db") == "pubmed"])
            == len(PROBE_IDS)
            and len([call for call in calls["efetch"] if call.get("db") == "pmc"])
            == len(PROBE_IDS)
            and len(calls["elink"]) == len(PROBE_IDS)
        )
        if not valid:
            raise PreflightError(
                "Maintained PubMed trace did not match the offline probe"
            )
    except BaseException as exc:
        error = exc
    finally:
        patches_restored = _network_restored(network_snapshot) and all(
            getattr(entrez, name) is value for name, value in original.items()
        )
        cache_empty = _remove_readiness_cache(cache_root, slug)
    if error is not None:
        raise error
    if not patches_restored:
        raise PreflightError("Readiness probe monkeypatches were not restored")
    if not cache_empty:
        raise PreflightError(
            "Readiness cache was not empty after removing probe artifacts"
        )
    return {
        "enabled": True,
        "run_id": run_id,
        "slug": slug,
        "path": str(trace_path),
        "sha256": trace_digest,
        "source_file_path": str(source_path),
        "server_build_id": tree_sha256,
        "process_id": pid,
        "sort": "pub_date",
        "selected_ids": PROBE_IDS,
        "final_ids": PROBE_IDS,
        "manifest_run_id": run_id,
        "manifest_ids": PROBE_IDS,
        "fake_entrez_calls": {name: len(values) for name, values in calls.items()},
        "patches_restored": patches_restored,
        "validated": True,
        "readiness_artifacts_removed": True,
        "cache_empty_after_cleanup": True,
    }


def _probe_transient_503(entrez: ModuleType) -> dict[str, Any]:
    _set_entrez_retry_policy(entrez)
    original_urlopen = getattr(entrez, "urlopen")
    network_snapshot = _network_snapshot()
    attempts = 0
    blocked: list[str] = []

    def fake_urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        url = getattr(request, "full_url", str(request))
        raise HTTPError(url, 503, "offline injected transient", None, None)

    with ExitStack() as stack:
        blocked = _guard_network(stack)
        stack.enter_context(_patch_attr(entrez, "urlopen", fake_urlopen))
        try:
            entrez._open(
                Request(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    method="GET",
                )
            )
        except HTTPError as error:
            if error.code != 503:
                raise PreflightError(
                    "Transient probe returned an unexpected HTTP status"
                ) from error
        else:
            raise PreflightError(
                "Transient probe did not receive its injected HTTP 503"
            )
    restored = getattr(entrez, "urlopen") is original_urlopen and _network_restored(
        network_snapshot
    )
    if attempts != 1 or not restored or blocked:
        raise PreflightError(
            "Entrez transient probe did not prove one restored attempt"
        )
    return {
        "patch_target": "Bio.Entrez.urlopen",
        "injected_status": 503,
        "underlying_attempts": attempts,
        "external_traffic": bool(blocked),
        "restored": restored,
    }


def _import_pinned_server(
    source_root: Path, entrez: ModuleType
) -> tuple[Any, Path, Path, Path, ModuleType, ModuleType]:
    if any(
        name == "mcp_server" or name.startswith("mcp_server.") for name in sys.modules
    ):
        raise PreflightError(
            "mcp_server is already imported; use a fresh launcher process"
        )
    engine_path = str(source_root / "engine")
    sys.path.insert(0, engine_path)
    package = __import__("mcp_server")
    pubmed_client = __import__("mcp_server.pubmed_client", fromlist=["*"])
    tool = __import__(
        "mcp_server.tools.lit_review.pubmed_search_with_fulltext", fromlist=["*"]
    )
    server = __import__("mcp_server.server", fromlist=["*"])
    package_path = Path(package.__file__).resolve()
    client_path = Path(pubmed_client.__file__).resolve()
    server_path = Path(server.__file__).resolve()
    tool_path = Path(tool.__file__).resolve()
    expected_package = source_root / "engine" / "mcp_server" / "__init__.py"
    expected_client = source_root / "engine" / "mcp_server" / "pubmed_client.py"
    expected_server = source_root / "engine" / "mcp_server" / "server.py"
    expected_tool = (
        source_root
        / "engine"
        / "mcp_server"
        / "tools"
        / "lit_review"
        / "pubmed_search_with_fulltext.py"
    )
    if (package_path, client_path, server_path, tool_path) != tuple(
        path.resolve()
        for path in (expected_package, expected_client, expected_server, expected_tool)
    ):
        raise PreflightError(
            "Imported MCP modules do not resolve to the pinned source root"
        )
    module_root = (source_root / "engine" / "mcp_server").resolve()
    if any(
        module_file
        and module_root not in Path(module_file).resolve().parents
        and Path(module_file).resolve() != module_root
        for name, module in sys.modules.items()
        if (name == "mcp_server" or name.startswith("mcp_server."))
        and (module_file := getattr(module, "__file__", None))
    ):
        raise PreflightError(
            "An MCP module was imported from outside the pinned source root"
        )
    if (entrez.max_tries, entrez.sleep_between_tries) != (1, 0):
        raise PreflightError(
            "Entrez retry settings changed during pinned server imports"
        )
    if getattr(entrez, "api_key", None):
        raise PreflightError("Entrez API key is present in the launcher process")
    app = getattr(server, "app", None)
    if app is None:
        raise PreflightError("Pinned MCP module does not expose its FastAPI app")
    return app, server_path, client_path, tool_path, pubmed_client, tool


def _atomic_write_json(path: Path, value: dict[str, Any], secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise PreflightError("Receipt path must be new")
    payload = json.dumps(value, sort_keys=True, indent=2) + "\n"
    if secret in payload:
        raise PreflightError("Refusing to write a receipt containing the shared secret")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _serve(app: Any, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, workers=1, reload=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--expected-tree-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source_root = args.source_root.expanduser().resolve(strict=True)
        if not source_root.is_dir() or args.source_root.is_symlink():
            raise PreflightError("Pinned source root must be a real directory")
        if not 1 <= args.port <= 65535:
            raise PreflightError("Loopback port is outside the valid range")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in (args.expected_tree_sha256, args.expected_source_sha256)
        ):
            raise PreflightError("Expected build hashes must be SHA-256 hex strings")
        tree_sha256 = _source_tree_sha256(source_root)
        if tree_sha256 != args.expected_tree_sha256:
            raise PreflightError("Pinned MCP source tree SHA-256 does not match")
        source_file = source_root / "engine" / "mcp_server" / "pubmed_client.py"
        server_file = source_root / "engine" / "mcp_server" / "server.py"
        source_sha256 = _sha256_file(source_file)
        if source_sha256 != args.expected_source_sha256:
            raise PreflightError("Pinned PubMed source SHA-256 does not match")
        if not server_file.is_file():
            raise PreflightError("Pinned MCP server module is missing")
        cache_root = _cache_root(args.cache_dir.expanduser())
        _require_outside(cache_root, (source_root,), "Cache")
        receipt_path = args.receipt.expanduser().resolve()
        _require_outside(receipt_path, (source_root, cache_root), "Receipt")
        if receipt_path.exists() or receipt_path.is_symlink():
            raise PreflightError("Receipt path must be new")
        secret, secret_length = _check_environment(source_root, cache_root, tree_sha256)

        from Bio import Entrez

        _set_entrez_retry_policy(Entrez)
        if getattr(Entrez, "api_key", None):
            raise PreflightError("Entrez API key is present in the launcher process")
        import_network_snapshot = _network_snapshot()
        with ExitStack() as import_guard:
            blocked_import = _guard_network(import_guard)
            (
                app,
                server_path,
                client_path,
                tool_path,
                pubmed_client,
                tool,
            ) = _import_pinned_server(source_root, Entrez)
        if blocked_import:
            raise PreflightError("Pinned MCP imports attempted external network access")
        import_guard_restored = _network_restored(import_network_snapshot)
        if not import_guard_restored:
            raise PreflightError("MCP import network guard was not restored")
        trace = _maintained_trace_probe(
            Entrez, tool, pubmed_client, cache_root, tree_sha256
        )
        transient = _probe_transient_503(Entrez)
        if (Entrez.max_tries, Entrez.sleep_between_tries) != (1, 0):
            raise PreflightError("Entrez retry policy changed after offline probes")
        if not trace["patches_restored"] or not transient["restored"]:
            raise PreflightError(
                "One or more offline probe monkeypatches remained active"
            )
        if _source_tree_sha256(source_root) != tree_sha256:
            raise PreflightError("Pinned MCP source tree changed during preflight")
        import uvicorn  # Prove serving dependency availability before receipt emission.

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "launcher_path": "references/external/sakana/novelty_precise_rung_server_launcher.py",
            "launcher_sha256": _sha256_file(Path(__file__).resolve()),
            "source_root": str(source_root),
            "source_tree_sha256": tree_sha256,
            "server_module": SERVER_MODULE,
            "server_file_path": str(server_path),
            "server_file_sha256": _sha256_file(server_path),
            "source_file_path": str(client_path),
            "source_file_sha256": source_sha256,
            "maintained_tool_file_path": str(tool_path),
            "maintained_tool_file_sha256": _sha256_file(tool_path),
            "serving_pid": os.getpid(),
            "bind_host": args.host,
            "bind_port": args.port,
            "max_workers": 1,
            "reload": False,
            "cache_root": str(cache_root),
            "trace_enabled": True,
            "environment": {
                CACHE_ENV: os.environ[CACHE_ENV],
                TRACE_ENV: os.environ[TRACE_ENV],
                BUILD_ENV: os.environ[BUILD_ENV],
            },
            "credential_env_names": [SECRET_ENV],
            "secret_env_name": SECRET_ENV,
            "secret_length": secret_length,
            "secret_free": True,
            "monkeypatches_restored": True,
            "import_network_guard_restored": import_guard_restored,
            "entrez": {
                "max_tries": Entrez.max_tries,
                "sleep_between_tries": Entrez.sleep_between_tries,
                "api_key_absent": True,
            },
            "maintained_trace": trace,
            "transient_probe": transient,
        }
        if _sha256_file(server_path) != receipt["server_file_sha256"]:
            raise PreflightError("Pinned server source changed during preflight")
        del uvicorn
        _atomic_write_json(receipt_path, receipt, secret)
    except Exception as error:
        print(
            f"Launcher stopped before serving: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 2
    _serve(app, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

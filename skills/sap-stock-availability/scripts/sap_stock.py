#!/usr/bin/env python3
"""sap_stock.py -- read-only CLI for the SAP stock availability skill.

Subcommands
-----------
  doctor                 check credentials, keystore backends and gateway reachability
  credentials set|forget|status
                         manage the stored password (getpass only, never printed)
  list                   print the scenario whitelist from catalog.json
  describe <FUNC>        parameter tree + SE37 long text + request skeleton
  call <FUNC> --payload  POST the payload through the REST2RFC gateway

Exit codes
----------
  0 ok | 2 payload rejected | 3 auth/credentials | 4 not registered
  5 timeout or oversized result | 1 other

Credentials come from the OS keystore (credential layer vendored from sap-adt-cli)
and are never printed. Only non-secret settings live in connection.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    sys.exit("requests is required: pip install requests")

# Credential layer vendored from sap-adt-cli. Backends are chosen by capability
# probing (env -> keyring -> dpapi -> pass -> file), never by platform.system():
# WSL reports "Linux" but the usable backend is Windows DPAPI.
from sap_credentials import (  # noqa: E402
    Credentials,  # __repr__/__str__ mask the password
    load_credentials,
    probe_keystores,
    select_keystore,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.json"
CONNECTION = ROOT / "connection.json"  # non-secret only: host / path / client / user / TLS
REQUIRED_CONN = ("host", "client", "user")

EXIT_OK, EXIT_PAYLOAD, EXIT_AUTH, EXIT_NOTREG, EXIT_LIMIT = 0, 2, 3, 4, 5


def fail(code: int, error: str, **extra: Any) -> None:
    """Emit a machine-readable error and stop. Never include credentials."""
    print(json.dumps({"ok": False, "error": error, **extra}, ensure_ascii=False, indent=2))
    sys.exit(code)


def load_conn() -> Dict[str, str]:
    """Read non-secret connection settings. No password ever lives here, so this
    file stays reviewable and can be pasted into an issue."""
    conn: Dict[str, str] = {}
    if CONNECTION.exists():
        conn.update(json.loads(CONNECTION.read_text(encoding="utf-8")))
    for key in ("host", "path", "client", "user", "verify", "ca_bundle", "timeout"):
        if os.environ.get(f"REST2RFC_{key.upper()}"):
            conn[key] = os.environ[f"REST2RFC_{key.upper()}"]
    missing = [k for k in REQUIRED_CONN if not conn.get(k)]
    if missing:
        fail(EXIT_AUTH, "CONFIG_MISSING", missing=missing,
             hint=f"fill {CONNECTION.name}; the password belongs in the OS keystore, not here")
    return conn


def cred_key(conn: Dict[str, str]) -> str:
    """No SID: this skill talks to an HTTP endpoint, so the identity is the
    endpoint plus the client plus the personal account."""
    return f"{conn['host']}|{conn['client']}:{conn['user']}"


def load_creds(conn: Dict[str, str], keystore: Optional[str] = None) -> Credentials:
    """Fail-closed: never fall back to a shared service account, never block on
    input in a non-interactive run."""
    try:
        return load_credentials(cred_key(conn), interactive=False, keystore=keystore)
    except LookupError:
        fail(EXIT_AUTH, "NO_CREDENTIAL", user=conn["user"],
             hint="run `sap_stock.py credentials set` to store the password in the OS keystore")
    except RuntimeError as exc:
        fail(EXIT_AUTH, "NO_KEYSTORE", detail=str(exc),
             hint="run `sap_stock.py doctor` to see the backend probe table")
    raise AssertionError("unreachable")


def verify_option(conn: Dict[str, str]) -> Any:
    """TLS verification defaults to OFF: these gateways normally sit on an
    internal self-signed cert. Setting ca_bundle turns verification back on
    automatically, and doctor prints the current state on every run."""
    bundle = conn.get("ca_bundle")
    if bundle:
        return bundle
    return str(conn.get("verify", "false")).lower() in ("1", "true", "yes")


def load_catalog() -> Dict[str, Any]:
    if not CATALOG.exists():
        fail(1, "CATALOG_MISSING", hint="catalog.json is the read-only whitelist")
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def resolve_entry(func: str) -> Dict[str, Any]:
    """Whitelist gate: anything outside catalog.json is refused locally."""
    entry = load_catalog().get("functions", {}).get(func.upper())
    if not entry:
        fail(EXIT_NOTREG, "NOT_IN_CATALOG", function=func.upper(),
             hint="this skill is read-only and scenario-scoped; "
                  "do not call functions outside catalog.json")
    return entry


def gateway_call(conn: Dict[str, str], creds: Credentials, func: str,
                 payload: Dict[str, Any]) -> Dict[str, Any]:
    """The dynamic gateway routes by RFC name: POST ...?RFC=<FUNCTION_NAME>."""
    base = conn["host"].rstrip("/") + conn.get("path", "/sap/bc/rest2rfc")
    try:
        resp = requests.post(
            base,
            params={"RFC": func, "sap-client": conn["client"]},
            auth=HTTPBasicAuth(creds.user, creds.password),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "Accept": "application/json"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            verify=verify_option(conn),
            timeout=int(conn.get("timeout", 60)),
        )
    except requests.exceptions.Timeout:
        fail(EXIT_LIMIT, "TIMEOUT", hint="narrow the selection (plant, date range) and retry")
    except requests.exceptions.SSLError as exc:
        fail(EXIT_AUTH, "TLS_ERROR", detail=str(exc)[:300],
             hint="point ca_bundle in connection.json at your corporate CA bundle")
    except requests.exceptions.RequestException as exc:
        fail(1, "NETWORK_ERROR", detail=str(exc)[:300])

    # Auth first: 401/403 must never be retried by the agent.
    if resp.status_code in (401, 403):
        fail(EXIT_AUTH, "AUTH_REQUIRED", status=resp.status_code, user=creds.user,
             hint="re-store the password with `credentials set`, and check that this personal "
                  "account holds S_RFC plus the read authorizations")
    if resp.status_code == 404:
        fail(EXIT_NOTREG, "NOT_REGISTERED", function=func,
             hint="add a ZTIF_GENERAL_CON row whose TASKFM is this function, with ACTFLG = X "
                  "and COMMITMODE = N; the gateway looks the row up by RFC name")
    if resp.status_code == 405:
        fail(1, "METHOD_NOT_ALLOWED", hint="the gateway only accepts POST")

    try:
        doc = json.loads(resp.text) if resp.text.strip() else {}
    except json.JSONDecodeError:
        fail(1, "NON_JSON_RESPONSE", status=resp.status_code, body=resp.text[:500])

    if resp.status_code >= 400:
        code = str(doc.get("error", "BAD_REQUEST"))
        exit_code = EXIT_PAYLOAD if code in (
            "BAD_REQUEST", "MISSING_PARAM", "UNKNOWN_PARAM",
            "TYPE_MISMATCH", "NOT_SUPPORTED") else 1
        fail(exit_code, code, status=resp.status_code, details=doc.get("details"),
             hint="re-read the interface with `describe` before rebuilding the payload")
    return doc


def truncate(doc: Dict[str, Any], max_rows: int) -> Dict[str, Any]:
    """Cap every table so a wide read cannot blow up the agent context."""
    out, notes = {}, []
    for key, value in doc.items():
        if isinstance(value, list) and len(value) > max_rows:
            out[key] = value[:max_rows]
            notes.append({"table": key, "returned": max_rows, "total": len(value)})
        else:
            out[key] = value
    return {"data": out, "truncated": notes}


def cmd_doctor(args: argparse.Namespace) -> int:
    conn = load_conn()
    creds = load_creds(conn, args.keystore)  # exits with 3 when nothing is stored
    probe = "BAPI_MATERIAL_GETLIST"
    resolve_entry(probe)  # the probe function must itself be whitelisted
    # Cheapest possible reachability probe: an intentionally empty payload.
    # A 2xx or a payload-level rejection both prove auth works.
    base = conn["host"].rstrip("/") + conn.get("path", "/sap/bc/rest2rfc")
    try:
        resp = requests.post(
            base, params={"RFC": probe, "sap-client": conn["client"]},
            auth=HTTPBasicAuth(creds.user, creds.password),
            data=b"{}", headers={"Content-Type": "application/json"},
            verify=verify_option(conn), timeout=20)
    except requests.exceptions.RequestException as exc:
        fail(1, "NETWORK_ERROR", detail=str(exc)[:300])
    if resp.status_code in (401, 403):
        fail(EXIT_AUTH, "AUTH_REQUIRED", status=resp.status_code, user=creds.user,
             hint="run `credentials set` again; the stored password no longer works")
    print(json.dumps({
        "ok": True,
        "host": conn["host"],                  # host / client / user are not secrets
        "client": conn["client"],
        "user": creds.user,                    # creds.password can never be printed
        "tls_verify": verify_option(conn),     # surfaced every run, never silently off
        "keystore": select_keystore(args.keystore).name,
        "keystore_probe": probe_keystores(),   # per-backend available? + readable reason
        "gateway_status": resp.status_code,
        "mode": load_catalog().get("mode"),
    }, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_credentials(args: argparse.Namespace) -> int:
    """Thin wrapper over the keystore. `status` reports configured or not
    configured only, and there is deliberately no `export` action."""
    from getpass import getpass

    conn = load_conn()
    try:
        store = select_keystore(args.keystore)
    except RuntimeError as exc:
        fail(EXIT_AUTH, "NO_KEYSTORE", detail=str(exc))
    key = cred_key(conn)
    if args.action == "set":
        if not store.writable:
            fail(EXIT_AUTH, "KEYSTORE_READONLY", keystore=store.name,
                 hint="the env backend cannot store secrets; pick another with --keystore")
        store.set(key, getpass(f"SAP password for {conn['user']}: "))
    elif args.action == "forget":
        store.delete(key)
    print(json.dumps({"ok": True, "keystore": store.name, "user": conn["user"],
                      "configured": store.get(key) is not None},
                     ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_list(_: argparse.Namespace) -> int:
    catalog = load_catalog()
    rows = [{"function": name, "required": e["required"], "semantics": e["semantics"]}
            for name, e in catalog.get("functions", {}).items()]
    print(json.dumps({"ok": True, "mode": catalog.get("mode"), "functions": rows},
                     ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_describe(args: argparse.Namespace) -> int:
    """Delegate to the vendored rest2rfc_meta.py from the gateway repository."""
    resolve_entry(args.function)
    conn = load_conn()
    creds = load_creds(conn, args.keystore)
    meta = Path(__file__).with_name("rest2rfc_meta.py")
    if not meta.exists():
        fail(1, "META_SCRIPT_MISSING", hint="vendor rest2rfc_meta.py from sap-rest2rfc-gateway")
    outdir = ROOT / ".cache"
    outdir.mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(meta), args.function.upper(), "--docs",
         "--outdir", str(outdir), "--password-stdin"],
        env={**os.environ,
             "REST2RFC_HOST": conn["host"],
             "REST2RFC_CLIENT": conn["client"],
             "REST2RFC_USER": creds.user},
        input=creds.password,  # password goes through stdin: argv is visible in ps
        capture_output=True, text=True)
    if proc.returncode != 0:
        blob = (proc.stderr or "")[-800:]
        if "401" in blob or "403" in blob:
            fail(EXIT_AUTH, "AUTH_REQUIRED",
                 hint="run `credentials set` to refresh the stored password")
        fail(1, "DESCRIBE_FAILED", detail=blob)
    stem = outdir / args.function.upper()
    for suffix in (".structure.txt", ".docs.md", ".request.json"):
        path = Path(str(stem) + suffix)
        if path.exists():
            print(f"===== {path.name} =====")
            print(path.read_text(encoding="utf-8"))
    return EXIT_OK


def cmd_call(args: argparse.Namespace) -> int:
    entry = resolve_entry(args.function)
    conn = load_conn()
    creds = load_creds(conn, args.keystore)
    raw = sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(EXIT_PAYLOAD, "INVALID_JSON", detail=str(exc))

    missing = [k for k in entry["required"] if not _present(payload, k)]
    if missing:
        fail(EXIT_PAYLOAD, "MISSING_PARAM", missing=missing,
             hint="ask the user for these values; do not invent defaults")

    doc = gateway_call(conn, creds, args.function.upper(), payload)
    result = truncate(doc, int(args.max_rows or entry.get("max_rows", 200)))
    print(json.dumps({"ok": True, "function": args.function.upper(),
                      "semantics": entry["semantics"], **result},
                     ensure_ascii=False, indent=2))
    return EXIT_OK


def _present(payload: Dict[str, Any], key: str) -> bool:
    """Required keys may sit at the top level or inside a structure parameter."""
    lowered = {str(k).lower(): v for k, v in payload.items()}
    if lowered.get(key.lower()) not in (None, "", [], {}):
        return True
    return any(
        isinstance(v, dict) and str(k).lower() != key.lower()
        and _present(v, key) for k, v in payload.items())


def main() -> int:
    parser = argparse.ArgumentParser(prog="sap_stock.py", description=__doc__)
    # Forcing a backend must error out when it is unavailable, never downgrade
    # silently -- otherwise neither tests nor support can reason about it.
    parser.add_argument("--keystore", default=None,
                        choices=["env", "keyring", "dpapi", "pass", "file"],
                        help="force a credential backend (default: capability probing)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check credentials, keystore backends and gateway reachability"
                   ).set_defaults(fn=cmd_doctor)
    sub.add_parser("list", help="print the scenario whitelist").set_defaults(fn=cmd_list)

    p_cred = sub.add_parser("credentials", help="store / remove / check the password")
    p_cred.add_argument("action", choices=["set", "forget", "status"])
    p_cred.set_defaults(fn=cmd_credentials)

    p_desc = sub.add_parser("describe", help="read the RFC interface and documentation")
    p_desc.add_argument("function")
    p_desc.set_defaults(fn=cmd_describe)

    p_call = sub.add_parser("call", help="call the gateway with a JSON payload")
    p_call.add_argument("function")
    p_call.add_argument("--payload", required=True, help="path to a JSON file, or - for stdin")
    p_call.add_argument("--max-rows", dest="max_rows", type=int, default=None)
    p_call.set_defaults(fn=cmd_call)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

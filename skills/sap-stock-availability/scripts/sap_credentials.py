#!/usr/bin/env python3
"""sap_credentials.py -- pluggable credential storage for the SAP stock skill.

API-COMPATIBLE SHIM
-------------------
This file exists so the skill runs standalone. The intended end state is to
replace it with the credential layer vendored from sap-adt-cli
(github.com/shrek-abaper/sap-engineering-skill/tree/main/skills/sap-adt-cli),
keeping these four exports:

    Credentials, load_credentials(), select_keystore(), probe_keystores()

If the vendored module's names differ, adapt THIS file, not sap_stock.py.

Design rules (do not relax):
  1. fail-closed -- no fallback to a shared account, no blocking prompt in a
     non-interactive run.
  2. Credentials masks the password in __repr__/__str__ (tracebacks are the
     most common real-world leak path for a CLI).
  3. Backends are picked by CAPABILITY PROBING, never by platform.system():
     WSL reports "Linux" but the usable backend is Windows DPAPI.
  4. No `export` action. Ever.

Backend order: env -> keyring -> dpapi -> pass -> file
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

STORE_DIR = Path(os.environ.get("SAP_STOCK_HOME", Path.home() / ".sap-stock"))
SERVICE = "sap-stock-availability"


@dataclass
class Credentials:
    """Password is masked everywhere a human or a log could see it."""

    user: str
    password: str = field(repr=False)

    def __repr__(self) -> str:  # noqa: D105
        return f"Credentials(user={self.user!r}, password='***')"

    __str__ = __repr__


class KeyStore:
    name = "base"
    writable = True

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def set(self, key: str, secret: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class EnvStore(KeyStore):
    """CI / containers. Read-only on purpose: core stays dependency-free."""

    name = "env"
    writable = False
    VAR = "REST2RFC_PASSWORD"

    def available(self) -> tuple[bool, str]:
        if os.environ.get(self.VAR):
            return True, f"{self.VAR} is set"
        return False, f"{self.VAR} not set"

    def get(self, key: str) -> Optional[str]:
        return os.environ.get(self.VAR) or None

    def set(self, key: str, secret: str) -> None:
        raise RuntimeError("the env backend cannot store secrets")

    def delete(self, key: str) -> None:
        raise RuntimeError("the env backend cannot delete secrets")


class KeyringStore(KeyStore):
    """Windows Credential Manager / macOS Keychain / Linux Secret Service.

    Availability requires a real handshake: importing `keyring` succeeds even
    when no usable backend exists (keyring.backends.fail.Keyring).
    """

    name = "keyring"

    def _mod(self):
        import keyring  # noqa: PLC0415

        return keyring

    def available(self) -> tuple[bool, str]:
        try:
            keyring = self._mod()
        except Exception as exc:  # noqa: BLE001
            return False, f"keyring not importable ({type(exc).__name__})"
        backend = keyring.get_keyring()
        if "fail.Keyring" in str(type(backend)):
            return False, "no usable keyring backend (fail.Keyring)"
        try:
            keyring.get_password(SERVICE, "__probe__")
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(backend).__name__} unusable ({type(exc).__name__})"
        return True, type(backend).__name__

    def get(self, key: str) -> Optional[str]:
        return self._mod().get_password(SERVICE, key)

    def set(self, key: str, secret: str) -> None:
        self._mod().set_password(SERVICE, key, secret)

    def delete(self, key: str) -> None:
        try:
            self._mod().delete_password(SERVICE, key)
        except Exception:  # noqa: BLE001
            pass


class DpapiStore(KeyStore):
    """WSL: encrypt through powershell.exe + Windows DPAPI (CurrentUser).

    The secret is passed on stdin, never on the command line -- argv is visible
    to any user via `ps` / Get-CimInstance.
    """

    name = "dpapi"
    FILE = STORE_DIR / "dpapi.json"

    def _pwsh(self) -> Optional[str]:
        return shutil.which("powershell.exe") or shutil.which("pwsh.exe")

    def available(self) -> tuple[bool, str]:
        if not self._pwsh():
            return False, "powershell.exe not reachable (not WSL?)"
        rc = subprocess.run(
            [self._pwsh(), "-NoProfile", "-Command",
             "[void][Reflection.Assembly]::LoadWithPartialName('System.Security'); 'ok'"],
            capture_output=True, text=True, timeout=30)
        if rc.returncode != 0:
            return False, "powershell.exe present but DPAPI probe failed"
        return True, "WSL + Windows DPAPI"

    def _run(self, script: str, stdin: str) -> str:
        proc = subprocess.run([self._pwsh(), "-NoProfile", "-Command", script],
                              input=stdin, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"dpapi call failed: {proc.stderr.strip()[:200]}")
        return proc.stdout.strip()

    def _load(self) -> Dict[str, str]:
        if self.FILE.exists():
            return json.loads(self.FILE.read_text(encoding="utf-8"))
        return {}

    def _save(self, blob: Dict[str, str]) -> None:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.FILE.write_text(json.dumps(blob), encoding="utf-8")
        _chmod_600(self.FILE)

    def get(self, key: str) -> Optional[str]:
        blob = self._load().get(key)
        if not blob:
            return None
        script = ("$e = [Console]::In.ReadToEnd().Trim();"
                  "$s = ConvertTo-SecureString -String $e;"
                  "$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
                  "[Runtime.InteropServices.Marshal]::PtrToStringAuto($b)")
        return self._run(script, blob)

    def set(self, key: str, secret: str) -> None:
        script = ("$p = [Console]::In.ReadToEnd().Trim();"
                  "ConvertTo-SecureString -String $p -AsPlainText -Force | ConvertFrom-SecureString")
        blob = self._load()
        blob[key] = self._run(script, secret)
        self._save(blob)

    def delete(self, key: str) -> None:
        blob = self._load()
        blob.pop(key, None)
        self._save(blob)


class PassStore(KeyStore):
    """headless Linux with GPG-backed `pass`."""

    name = "pass"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("pass"):
            return False, "`pass` not installed"
        return True, "pass + gpg"

    def get(self, key: str) -> Optional[str]:
        proc = subprocess.run(["pass", "show", f"{SERVICE}/{key}"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        return proc.stdout.splitlines()[0] if proc.stdout else None

    def set(self, key: str, secret: str) -> None:
        subprocess.run(["pass", "insert", "--multiline", "--force", f"{SERVICE}/{key}"],
                       input=secret + "\n", text=True, check=True)

    def delete(self, key: str) -> None:
        subprocess.run(["pass", "rm", "--force", f"{SERVICE}/{key}"],
                       capture_output=True, text=True)


class FileStore(KeyStore):
    """Last resort. A passphrase is MANDATORY: an 'encrypted' file whose key
    sits next to it is plaintext with extra steps. scrypt + AES-GCM (Fernet).
    """

    name = "file"
    FILE = STORE_DIR / "secrets.json"
    ENV_PASSPHRASE = "SAP_STOCK_PASSPHRASE"

    def available(self) -> tuple[bool, str]:
        try:
            import cryptography  # noqa: F401,PLC0415
        except ImportError:
            return False, "cryptography not installed (pip install cryptography)"
        return True, "available (requires passphrase)"

    def _fernet(self, salt: bytes):
        from cryptography.fernet import Fernet  # noqa: PLC0415
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt  # noqa: PLC0415

        passphrase = os.environ.get(self.ENV_PASSPHRASE)
        if not passphrase:
            if not sys.stdin.isatty():
                raise RuntimeError(
                    f"{self.ENV_PASSPHRASE} is not set and the run is non-interactive")
            from getpass import getpass  # noqa: PLC0415

            passphrase = getpass("File store passphrase: ")
        key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())
        return Fernet(base64.urlsafe_b64encode(key))

    def _load(self) -> Dict[str, object]:
        if self.FILE.exists():
            return json.loads(self.FILE.read_text(encoding="utf-8"))
        return {"salt": base64.b64encode(os.urandom(16)).decode(), "items": {}}

    def get(self, key: str) -> Optional[str]:
        blob = self._load()
        token = blob["items"].get(key)  # type: ignore[union-attr]
        if not token:
            return None
        fernet = self._fernet(base64.b64decode(blob["salt"]))  # type: ignore[arg-type]
        return fernet.decrypt(token.encode()).decode()

    def set(self, key: str, secret: str) -> None:
        blob = self._load()
        fernet = self._fernet(base64.b64decode(blob["salt"]))  # type: ignore[arg-type]
        blob["items"][key] = fernet.encrypt(secret.encode()).decode()  # type: ignore[index]
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.FILE.write_text(json.dumps(blob), encoding="utf-8")
        _chmod_600(self.FILE)

    def delete(self, key: str) -> None:
        blob = self._load()
        blob["items"].pop(key, None)  # type: ignore[union-attr]
        self.FILE.write_text(json.dumps(blob), encoding="utf-8")
        _chmod_600(self.FILE)


def _chmod_600(path: Path) -> None:
    """chmod is a no-op on DrvFs (/mnt/c). Report it instead of pretending."""
    try:
        path.chmod(0o600)
    except OSError:
        pass


ORDER: List[KeyStore] = [EnvStore(), KeyringStore(), DpapiStore(), PassStore(), FileStore()]


def probe_keystores() -> List[Dict[str, object]]:
    """Every backend plus a human-readable reason. Most cross-platform support
    tickets are really 'nobody knows which backend was used'."""
    out = []
    for store in ORDER:
        try:
            ok, reason = store.available()
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"probe raised {type(exc).__name__}"
        out.append({"backend": store.name, "available": ok, "reason": reason,
                    "writable": store.writable})
    return out


def select_keystore(name: Optional[str] = None) -> KeyStore:
    """Forcing an unavailable backend is an error, never a silent downgrade."""
    if name:
        for store in ORDER:
            if store.name == name:
                ok, reason = store.available()
                if not ok:
                    raise RuntimeError(f"keystore '{name}' is unavailable: {reason}")
                return store
        raise RuntimeError(f"unknown keystore '{name}'")
    for store in ORDER:
        try:
            if store.available()[0]:
                return store
        except Exception:  # noqa: BLE001,S112
            continue
    raise RuntimeError("no usable credential backend; run `doctor` for the probe table")


def load_credentials(key: str, interactive: bool = False,
                     keystore: Optional[str] = None) -> Credentials:
    """key format: '<host>|<client>:<user>' (no SID: this skill talks to an HTTP
    endpoint, so a SID would be a field nothing can validate).

    Raises LookupError when nothing is stored -- the caller turns that into exit
    code 3. It never falls back to another account and never prompts unless
    interactive=True AND a tty is attached.
    """
    user = key.rsplit(":", 1)[-1]
    store = select_keystore(keystore)
    secret = store.get(key)
    if secret:
        return Credentials(user=user, password=secret)
    if interactive and sys.stdin.isatty():
        from getpass import getpass  # noqa: PLC0415

        return Credentials(user=user, password=getpass(f"SAP password for {user}: "))
    raise LookupError(f"no credential stored for {user} in backend '{store.name}'")

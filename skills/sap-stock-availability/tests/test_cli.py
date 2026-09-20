"""Offline tests for the RFC_READ_TABLE fallback guard.

No network and no SAP credentials are needed: guard_table_read runs before
the gateway call and is where the local read-only contract is enforced.
Run from the skill directory:  python3 -m pytest tests/
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sap_stock  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[1]


def _fallback_entry():
    catalog = json.loads((SKILL_ROOT / "catalog.json").read_text(encoding="utf-8"))
    entry = catalog["functions"]["RFC_READ_TABLE"]
    assert entry.get("fallback") is True
    return entry


def _payload(table="MARD", fields=None, options=None, rowcount=None):
    payload = {
        "query_table": table,
        "fields": fields if fields is not None else [{"fieldname": "LABST"}],
        "options": options if options is not None else [
            {"text": "MATNR = 'P0274635AB' AND WERKS = '5260'"}],
    }
    if rowcount is not None:
        payload["rowcount"] = rowcount
    return payload


def _guard_error(entry, payload):
    with pytest.raises(SystemExit) as exc:
        sap_stock.guard_table_read(entry, payload)
    assert exc.value.code == sap_stock.EXIT_PAYLOAD
    return exc


def test_catalog_fallback_declared():
    entry = _fallback_entry()
    assert "MARD" in entry["table_allowlist"]
    assert entry["max_rows"] == 100


def test_table_not_allowlisted_rejected(capsys):
    _guard_error(_fallback_entry(), _payload(table="USR02"))
    assert "TABLE_NOT_ALLOWED" in capsys.readouterr().err


def test_empty_field_list_rejected(capsys):
    # Call the guard directly (catalog required-check would otherwise win).
    entry = {"table_allowlist": ["MARD"], "max_rows": 100}
    _guard_error(entry, _payload(fields=[]))
    assert "EMPTY_FIELD_LIST" in capsys.readouterr().err


def test_missing_filter_rejected(capsys):
    _guard_error(_fallback_entry(), _payload(options=[]))
    assert "MISSING_FILTER" in capsys.readouterr().err


def test_where_line_over_72_chars_rejected(capsys):
    long_where = "MATNR = 'P0274635AB' AND WERKS = '5260' AND LGORT IN ('0001','0002','0003')"
    assert len(long_where) > 72
    _guard_error(_fallback_entry(), _payload(options=[{"text": long_where}]))
    assert "OPTION_LINE_TOO_LONG" in capsys.readouterr().err


def test_plant_table_requires_werks(capsys):
    payload = _payload(options=[{"text": "MATNR = 'P0274635AB'"}])
    _guard_error(_fallback_entry(), payload)
    assert "MISSING_KEY_FILTER" in capsys.readouterr().err


def test_marm_allows_matnr_only():
    payload = _payload(table="MARM", options=[{"text": "MATNR = 'P0274635AB'"}])
    sap_stock.guard_table_read(_fallback_entry(), payload)  # must not raise


def test_rowcount_over_cap_rejected(capsys):
    _guard_error(_fallback_entry(), _payload(rowcount="101"))
    assert "ROWCOUNT_EXCEEDS_CAP" in capsys.readouterr().err


def test_rowcount_injected_when_absent():
    payload = _payload()
    sap_stock.guard_table_read(_fallback_entry(), payload)
    assert payload["rowcount"] == "100"


def test_valid_payload_passes():
    payload = _payload(rowcount="50")
    sap_stock.guard_table_read(_fallback_entry(), payload)


def test_fail_writes_stderr_not_stdout(capsys):
    with pytest.raises(SystemExit) as exc:
        sap_stock.fail(sap_stock.EXIT_AUTH, "NO_CREDENTIAL", user="t")
    assert exc.value.code == sap_stock.EXIT_AUTH
    captured = capsys.readouterr()
    assert "NO_CREDENTIAL" in captured.err
    assert captured.out == ""
    assert "t" in captured.err  # username is fine, the password is never passed

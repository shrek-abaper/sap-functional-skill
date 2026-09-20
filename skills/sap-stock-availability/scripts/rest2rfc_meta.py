#!/usr/bin/env python3
"""
rest2rfc_meta.py -- read the interface of an RFC / BAPI through the
REST2RFC gateway and print a reference JSON payload for it.

Flow
----
1. POST to the gateway with ACTION = <meta action>, calling
   RFC_METADATA_GET with FUNCTIONNAMES = [ <function> ] and DEEP = 'X'.
2. Build a type registry from the returned DATATYPES / DATATYPESCONT
   tables and resolve every parameter type recursively.
3. Any type the metadata call did not deliver is resolved through a
   second gateway action calling DDIF_FIELDINFO_GET (ALL_TYPES = 'X').
4. With --docs, read the SE37 long documentation through a third action
   calling DOCU_READ (documentation class 'FU') and convert the SAPscript
   ITF lines to plain Markdown.
5. Print / write:
     <FUNC>.structure.txt   full parameter tree
     <FUNC>.request.json    sample request payload  (I / C / T)
     <FUNC>.response.json   expected response shape (E / C / T)
     <FUNC>.docs.md         SE37 documentation      (--docs only)
     <FUNC>.raw.json        raw metadata            (--dump only)

Prerequisites in SAP
--------------------
Rows in ZTIF_GENERAL_CON, all read only, LOGFLG empty:

  IFCODE     TASKFM                 ACTFLG  COMMITMODE
  SYS_META   RFC_METADATA_GET       X       N
  SYS_DDIC   DDIF_FIELDINFO_GET     X       N
  SYS_DOCU   DOCU_READ              X       N       (only for --docs)

DOCU_READ and DDIF_FIELDINFO_GET are not remote enabled in every release.
That does not matter here: the gateway issues a local CALL FUNCTION, so
the RFC attribute is irrelevant.

Usage
-----
  export REST2RFC_HOST=https://sap-dev.example.com:44300
  export REST2RFC_USER=RFCUSER
  export REST2RFC_PASSWORD=secret
  export REST2RFC_CLIENT=100

  python3 rest2rfc_meta.py BAPI_PO_GETDETAIL
  python3 rest2rfc_meta.py BAPI_PO_GETDETAIL --docs
  python3 rest2rfc_meta.py BAPI_MATERIAL_SAVEDATA --docs --dump --outdir ./out

No credentials are ever written to the output files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:  # pragma: no cover
    sys.exit("requests is required:  pip install requests")


# ---------------------------------------------------------------------------
# Key tolerance
#
# The exact column names of the RFC_METADATA_GET tables differ between
# releases, and the gateway lower cases every key. Instead of hard coding
# one spelling, every lookup tries a list of candidates. Run with --dump
# once and extend these lists if your release uses different names.
# ---------------------------------------------------------------------------

K_FUNCNAME = ("funcname", "functionname", "name")
K_PARAM = ("parameter", "paramname", "parametername", "name")
K_PARAMCLASS = ("paramclass", "class", "paramtype", "kind")
K_TYPENAME = ("typename", "type_name", "tabname", "structure", "type", "reftype")
K_FIELDNAME = ("fieldname", "field", "name")
K_NESTED = ("typename2", "reftype", "refname", "tabname", "structure", "linetype", "rowtype")
K_EXID = ("exid", "typekind", "inttype", "datatype", "type")
K_LENGTH = ("leng", "length", "intlength", "intlen", "len")
K_DECIMALS = ("decimals", "dec", "decs")
K_OPTIONAL = ("optional", "paramoptional", "opt")
K_TEXT = ("paramtext", "fieldtext", "text", "scrtext_m")

# Table names inside the RFC_METADATA_GET answer.
T_PARAMETERS = ("parameters", "params", "params_p")
T_DATATYPES = ("datatypes", "types")
T_DATATYPESCONT = ("datatypescont", "datatypecont", "typescont", "fields")
T_FUNC_ERRORS = ("func_errors", "funcerrors")
T_DD_ERRORS = ("dd_errors", "dderrors")

# DOCU_READ answer.
T_DOCU_LINE = ("line", "lines", "tline", "itf")
K_TDFORMAT = ("tdformat", "format")
K_TDLINE = ("tdline", "line", "text")


def pick(row: Dict[str, Any], candidates: Sequence[str], default: Any = "") -> Any:
    """Return the first present, non empty value among candidates."""
    if not isinstance(row, dict):
        return default
    lowered = {str(k).lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand in lowered:
            val = lowered[cand]
            if val not in (None, ""):
                return val
    return default


def pick_table(doc: Dict[str, Any], candidates: Sequence[str]) -> List[Dict[str, Any]]:
    """Return a table from the gateway answer, tolerating key spelling."""
    lowered = {str(k).lower(): v for k, v in doc.items()}
    for cand in candidates:
        val = lowered.get(cand)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            return [val]
    return []


def pick_value(doc: Dict[str, Any], candidates: Sequence[str], default: Any = "") -> Any:
    return pick(doc, candidates, default)


# ---------------------------------------------------------------------------
# Placeholder values per ABAP type
# ---------------------------------------------------------------------------

NUMERIC_DATATYPES = {"DEC", "CURR", "QUAN", "FLTP", "INT1", "INT2", "INT4", "INT8", "PREC"}
NUMERIC_EXID = set("IbsP8Fae")   # ABAP internal type kinds that are numeric


def placeholder(datatype: str, exid: str, length: Any, decimals: Any) -> Any:
    dt = (str(datatype) or "").strip().upper()
    ex = (str(exid) or "").strip()

    if dt == "DATS" or ex == "D":
        return "20260101"
    if dt == "TIMS" or ex == "T":
        return "000000"
    if dt in ("RAW", "RAWSTRING") or ex in ("X", "y"):
        return ""
    if dt == "NUMC":
        # NUMC stays a string, leading zeros are significant
        return ""
    if dt in NUMERIC_DATATYPES or ex in NUMERIC_EXID:
        try:
            return 0.0 if int(decimals or 0) > 0 else 0
        except (TypeError, ValueError):
            return 0
    return ""


# ---------------------------------------------------------------------------
# Gateway client
# ---------------------------------------------------------------------------

class GatewayError(RuntimeError):
    pass


class Gateway:
    def __init__(self, host: str, user: str, password: str, client: str,
                 path: str = "/sap/bc/rest2rfc", verify: bool = True,
                 timeout: int = 60, verbose: bool = False) -> None:
        self.base = host.rstrip("/") + path
        self.client = client
        self.verify = verify
        self.timeout = timeout
        self.verbose = verbose
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user, password)
        self.session.headers.update({"Content-Type": "application/json; charset=utf-8",
                                     "Accept": "application/json"})

    def call(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Dynamic gateway contract: the FM name travels in ?RFC=<FM>, and the
        # registry row (ZTIF_GENERAL_CON-TASKFM) is looked up by that name.
        params = {"RFC": action}
        if self.client:
            params["sap-client"] = self.client
        if self.verbose:
            print(f"--> POST {self.base}?RFC={action}", file=sys.stderr)
            print(json.dumps(payload, indent=2, ensure_ascii=False)[:2000], file=sys.stderr)

        resp = self.session.post(self.base, params=params,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 verify=self.verify, timeout=self.timeout)
        body = resp.text or ""
        try:
            doc = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            raise GatewayError(f"HTTP {resp.status_code}, body is not JSON:\n{body[:2000]}")

        if resp.status_code >= 400:
            # The gateway answers 400 with {"error":"BAD_REQUEST","details":[...]}
            detail = json.dumps(doc, indent=2, ensure_ascii=False)[:2000] if doc else body[:2000]
            raise GatewayError(f"HTTP {resp.status_code} {resp.reason}\n{detail}")
        if not isinstance(doc, dict):
            raise GatewayError(f"Unexpected answer shape: {type(doc).__name__}")
        return doc


# ---------------------------------------------------------------------------
# Metadata resolution
# ---------------------------------------------------------------------------

class Resolver:
    def __init__(self, gw: Gateway, action_ddic: Optional[str],
                 max_depth: int = 12, verbose: bool = False) -> None:
        self.gw = gw
        self.action_ddic = action_ddic
        self.max_depth = max_depth
        self.verbose = verbose
        self.fields_by_type: Dict[str, List[Dict[str, Any]]] = {}
        self.type_header: Dict[str, Dict[str, Any]] = {}
        self.ddic_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.unresolved: List[str] = []

    # -- registry -----------------------------------------------------------

    def load_registry(self, doc: Dict[str, Any]) -> None:
        for row in pick_table(doc, T_DATATYPES):
            name = str(pick(row, K_TYPENAME)).upper()
            if name:
                self.type_header[name] = row
        for row in pick_table(doc, T_DATATYPESCONT):
            name = str(pick(row, K_TYPENAME)).upper()
            if name:
                self.fields_by_type.setdefault(name, []).append(row)

    # -- DDIC fallback ------------------------------------------------------

    def ddic_fields(self, type_name: str) -> List[Dict[str, Any]]:
        key = type_name.upper()
        if key in self.ddic_cache:
            return self.ddic_cache[key]
        if not self.action_ddic:
            self.ddic_cache[key] = []
            return []
        try:
            doc = self.gw.call(self.action_ddic, {
                "tabname": key,
                "all_types": "X",
                "langu": "E",
                "dfies_tab": [],
            })
        except GatewayError as exc:
            if self.verbose:
                print(f"    DDIC lookup failed for {key}: {exc}", file=sys.stderr)
            self.ddic_cache[key] = []
            return []
        rows = pick_table(doc, ("dfies_tab", "dfies", "fields"))
        self.ddic_cache[key] = rows
        return rows

    # -- recursion ----------------------------------------------------------

    def resolve(self, type_name: str, depth: int = 0,
                seen: Optional[Tuple[str, ...]] = None) -> Optional[List[Dict[str, Any]]]:
        """Return a list of resolved field descriptors, or None for a scalar."""
        seen = seen or ()
        key = (type_name or "").upper()
        if not key or depth > self.max_depth:
            return None
        if key in seen:                      # recursive type, stop here
            return []

        rows = self.fields_by_type.get(key) or self.ddic_fields(key)
        if not rows:
            if key and key not in self.unresolved and "-" not in key:
                self.unresolved.append(key)
            return None

        out: List[Dict[str, Any]] = []
        for row in rows:
            fname = str(pick(row, K_FIELDNAME)).strip()
            if not fname:
                continue
            nested = str(pick(row, K_NESTED)).strip().upper()
            datatype = str(pick(row, ("datatype",) + K_EXID)).strip()
            exid = str(pick(row, K_EXID)).strip()
            length = pick(row, K_LENGTH, 0)
            decimals = pick(row, K_DECIMALS, 0)

            child: Optional[List[Dict[str, Any]]] = None
            if nested and nested != key:
                child = self.resolve(nested, depth + 1, seen + (key,))

            out.append({
                "name": fname,
                "type": nested or datatype,
                "datatype": datatype,
                "exid": exid,
                "length": length,
                "decimals": decimals,
                "text": str(pick(row, K_TEXT)),
                "fields": child,
                "is_table": is_table_kind(row),
            })
        return out


def is_table_kind(row: Dict[str, Any]) -> bool:
    kind = str(pick(row, ("typekind", "exid", "inttype"))).strip()
    return kind in ("h", "H")


# ---------------------------------------------------------------------------
# SE37 documentation (DOCU_READ, documentation class 'FU')
#
# Object names:
#   function level  : OBJECT = <FUNCNAME>
#   parameter level : OBJECT = <FUNCNAME padded to 30><PARAMETER>
# The padded form is what the Function Builder uses; if a release stores
# it differently the reader falls back to '<FUNCNAME> <PARAMETER>'.
# Run with --verbose to see which form answered.
# ---------------------------------------------------------------------------

ITF_TAG = re.compile(r"<[^<>]{1,40}>")           # <ZH>, <AB>, <DS:...>, <(>, <)>
ITF_HEADINGS = {"U1": "## ", "U2": "### ", "U3": "#### "}
ITF_BULLETS = {"B1": "- ", "B2": "  - ", "AS": "- ", "LI": "- "}


def itf_to_markdown(lines: List[Dict[str, Any]]) -> str:
    """Convert TLINE rows (TDFORMAT / TDLINE) into readable Markdown."""
    out: List[str] = []
    for row in lines:
        fmt = str(pick(row, K_TDFORMAT)).strip().upper()
        text = str(pick(row, K_TDLINE, ""))
        text = ITF_TAG.sub("", text).rstrip()
        if fmt == "=" and out:                       # continuation of previous line
            out[-1] = (out[-1] + " " + text.strip()).rstrip()
            continue
        if not text:
            out.append("")
            continue
        prefix = ITF_HEADINGS.get(fmt) or ITF_BULLETS.get(fmt, "")
        out.append(prefix + text.strip())
    # collapse runs of blank lines
    cleaned: List[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


class DocReader:
    def __init__(self, gw: Gateway, action: Optional[str], langu: str = "E",
                 verbose: bool = False) -> None:
        self.gw = gw
        self.action = action
        self.langu = langu
        self.verbose = verbose
        self.raw: Dict[str, Any] = {}

    def _read(self, obj: str) -> Tuple[str, str]:
        """Return (title, markdown) for one documentation object."""
        if not self.action:
            return "", ""
        payload = {
            "id": "FU",
            "langu": self.langu,
            "object": obj,
            "typ": "E",
            "line": [],
        }
        try:
            doc = self.gw.call(self.action, payload)
        except GatewayError as exc:
            if self.verbose:
                print(f"    DOCU_READ failed for '{obj}': {exc}", file=sys.stderr)
            return "", ""
        self.raw[obj] = doc
        state = str(pick_value(doc, ("dokstate", "state"))).strip().upper()
        title = str(pick_value(doc, ("doktitle", "title")))
        lines = pick_table(doc, T_DOCU_LINE)
        if state in ("D", "") and not lines:     # D = deleted / not available
            return title, ""
        return title, itf_to_markdown(lines)

    def function_doc(self, funcname: str) -> Tuple[str, str]:
        return self._read(funcname.upper())

    def parameter_doc(self, funcname: str, parameter: str) -> str:
        func = funcname.upper()
        param = parameter.upper()
        for obj in (func.ljust(30) + param, f"{func} {param}"):
            _, text = self._read(obj)
            if text:
                if self.verbose:
                    print(f"    doc found for {param} via '{obj.strip()}'", file=sys.stderr)
                return text
        return ""


def render_docs(funcname: str, title: str, body: str,
                params: List[Dict[str, Any]],
                param_docs: Dict[str, str]) -> str:
    out: List[str] = [f"# {funcname.upper()}"]
    if title:
        out.append(f"\n{title}")
    # SE37 documentation usually starts with its own U1 heading; do not add
    # a second one on top of it.
    if body.lstrip().startswith("#"):
        out.append("\n" + body)
    else:
        out.append("\n## Functionality\n")
        out.append(body or "_no function documentation in this language_")
    out.append("\n## Parameters\n")
    for p in params:
        flag = "optional" if p["optional"] else "mandatory"
        out.append(f"### {p['name']}  ({CLASS_TEXT.get(p['paramclass'], p['paramclass'])}, "
                   f"{p['type']}, {flag})\n")
        if p["text"]:
            out.append(f"{p['text']}\n")
        doc = param_docs.get(p["name"], "")
        out.append((doc or "_no long text_") + "\n")
    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------------------
# Sample building
# ---------------------------------------------------------------------------

def sample_from_fields(fields: Optional[List[Dict[str, Any]]]) -> Any:
    if fields is None:
        return ""
    out: Dict[str, Any] = {}
    for f in fields:
        key = f["name"].lower()
        if f["fields"] is not None:
            value: Any = sample_from_fields(f["fields"])
            if f["is_table"]:
                value = [value]
        else:
            value = placeholder(f["datatype"], f["exid"], f["length"], f["decimals"])
        out[key] = value
    return out


def build_param_list(doc: Dict[str, Any], funcname: str,
                     resolver: Resolver) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []
    for row in pick_table(doc, T_PARAMETERS):
        owner = str(pick(row, K_FUNCNAME)).upper()
        if owner and owner != funcname.upper():
            continue
        name = str(pick(row, K_PARAM)).strip()
        if not name:
            continue
        pclass = str(pick(row, K_PARAMCLASS)).strip().upper()[:1]
        if pclass == "X":                    # classic exception, not a parameter
            continue
        type_name = str(pick(row, K_TYPENAME)).strip().upper()
        fieldname = str(pick(row, ("fieldname",))).strip().upper()
        full_type = f"{type_name}-{fieldname}" if fieldname else type_name

        # A parameter typed TABNAME-FIELDNAME is a scalar: never resolve the
        # owning structure, that would add a pointless DDIC round trip and a
        # false entry in the unresolved list.
        fields = None
        if type_name and not fieldname:
            fields = resolver.resolve(type_name)

        params.append({
            "name": name.upper(),
            "paramclass": pclass or "I",
            "type": full_type,
            "datatype": str(pick(row, ("datatype",))),
            "exid": str(pick(row, K_EXID)),
            "length": pick(row, K_LENGTH, 0),
            "decimals": pick(row, K_DECIMALS, 0),
            "optional": str(pick(row, K_OPTIONAL)).strip().upper() in ("X", "TRUE", "1"),
            "text": str(pick(row, K_TEXT)),
            "fields": fields,
        })
    params.sort(key=lambda p: ("ICTE".find(p["paramclass"]), p["name"]))
    return params


def sample_payload(params: List[Dict[str, Any]], classes: str,
                   skip_optional: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for p in params:
        if p["paramclass"] not in classes:
            continue
        if skip_optional and p["optional"]:
            continue
        if p["paramclass"] == "T":
            body = sample_from_fields(p["fields"]) if p["fields"] is not None else ""
            out[p["name"].lower()] = [body] if body != "" else []
        elif p["fields"] is not None:
            out[p["name"].lower()] = sample_from_fields(p["fields"])
        else:
            out[p["name"].lower()] = placeholder(p["datatype"], p["exid"],
                                                 p["length"], p["decimals"])
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

CLASS_TEXT = {"I": "IMPORTING", "E": "EXPORTING", "C": "CHANGING", "T": "TABLES"}


def render_tree(funcname: str, params: List[Dict[str, Any]],
                unresolved: List[str], title: str = "") -> str:
    lines: List[str] = []
    lines.append(f"FUNCTION {funcname.upper()}")
    lines.append("=" * (9 + len(funcname)))
    if title:
        lines.append(title)
    lines.append("")
    for pclass in "ICTE":
        group = [p for p in params if p["paramclass"] == pclass]
        if not group:
            continue
        lines.append(f"{CLASS_TEXT.get(pclass, pclass)}")
        for p in group:
            flag = "optional" if p["optional"] else "MANDATORY"
            shape = "table" if p["paramclass"] == "T" else (
                "structure" if p["fields"] is not None else "scalar")
            lines.append(f"  {p['name']:<30} {p['type']:<30} {shape:<10} {flag}")
            if p["text"]:
                lines.append(f"      \"{p['text']}\"")
            if p["fields"]:
                lines.extend(render_fields(p["fields"], 2))
        lines.append("")
    if unresolved:
        lines.append("UNRESOLVED TYPES (treated as scalars)")
        for t in unresolved:
            lines.append(f"  {t}")
        lines.append("")
    return "\n".join(lines)


def render_fields(fields: List[Dict[str, Any]], level: int) -> List[str]:
    out: List[str] = []
    pad = "  " * (level + 1)
    for f in fields:
        desc = f"{f['datatype']}({f['length']}"
        desc += f",{f['decimals']})" if str(f["decimals"]) not in ("0", "") else ")"
        shape = "[]" if f["is_table"] else ""
        out.append(f"{pad}{f['name']:<28}{shape:<3}{desc:<16}{f['text'][:40]}")
        if f["fields"]:
            out.extend(render_fields(f["fields"], level + 1))
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read an RFC / BAPI interface through the REST2RFC gateway "
                    "and generate a reference JSON payload.")
    p.add_argument("function", help="function module name, e.g. BAPI_PO_GETDETAIL")
    p.add_argument("--host", default=os.environ.get("REST2RFC_HOST", ""),
                   help="https://host:port  (env REST2RFC_HOST)")
    p.add_argument("--path", default=os.environ.get("REST2RFC_PATH", "/sap/bc/rest2rfc"),
                   help="ICF path of the gateway")
    p.add_argument("--client", default=os.environ.get("REST2RFC_CLIENT", ""),
                   help="sap-client (env REST2RFC_CLIENT)")
    p.add_argument("--user", default=os.environ.get("REST2RFC_USER", ""),
                   help="user (env REST2RFC_USER)")
    p.add_argument("--password", default=os.environ.get("REST2RFC_PASSWORD", ""),
                   help="password (env REST2RFC_PASSWORD)")
    p.add_argument("--password-stdin", action="store_true",
                   help="read the password from stdin (keeps argv ps-safe)")
    p.add_argument("--action-meta", default=os.environ.get("REST2RFC_ACTION_META", "RFC_METADATA_GET"),
                   help="FM name registered for metadata (ZTIF_GENERAL_CON-TASKFM)")
    p.add_argument("--action-ddic", default=os.environ.get("REST2RFC_ACTION_DDIC", "DDIF_FIELDINFO_GET"),
                   help="FM registered for DDIC fallback, empty to disable")
    p.add_argument("--action-docu", default=os.environ.get("REST2RFC_ACTION_DOCU", "DOCU_READ"),
                   help="FM registered for DOCU_READ, used by --docs")
    p.add_argument("--docs", action="store_true",
                   help="also read the SE37 long documentation (function and parameters)")
    p.add_argument("--docs-lang", default="",
                   help="documentation language, defaults to --language")
    p.add_argument("--language", default="E")
    p.add_argument("--outdir", default=".")
    p.add_argument("--print", dest="print_what", default="all",
                   choices=("all", "tree", "request", "response", "docs", "none"))
    p.add_argument("--mandatory-only", action="store_true",
                   help="sample request contains mandatory parameters only")
    p.add_argument("--max-depth", type=int, default=12)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    p.add_argument("--dump", action="store_true", help="also write the raw metadata answer")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.password_stdin:
        args.password = sys.stdin.read().rstrip("\r\n")
    missing = [n for n, v in (("--host", args.host), ("--user", args.user),
                              ("--password", args.password)) if not v]
    if missing:
        print(f"missing: {', '.join(missing)}  (or the matching REST2RFC_* variables)",
              file=sys.stderr)
        return 2

    if args.insecure:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    funcname = args.function.upper()
    gw = Gateway(args.host, args.user, args.password, args.client,
                 path=args.path, verify=not args.insecure,
                 timeout=args.timeout, verbose=args.verbose)

    payload = {
        "deep": "X",
        "language": args.language,
        "evaluate_links": "X",
        "functionnames": [{"functionname": funcname}],
        "parameters": [],
        "datatypes": [],
        "datatypescont": [],
        "known_datatypes": [],
        "indirecttypes": [],
        "func_errors": [],
        "dd_errors": [],
    }

    try:
        doc = gw.call(args.action_meta, payload)
    except GatewayError as exc:
        print(f"RFC_METADATA_GET failed: {exc}", file=sys.stderr)
        return 1

    for tab, label in ((T_FUNC_ERRORS, "FUNC_ERRORS"), (T_DD_ERRORS, "DD_ERRORS")):
        rows = pick_table(doc, tab)
        if rows:
            print(f"{label}: {json.dumps(rows, ensure_ascii=False)}", file=sys.stderr)

    resolver = Resolver(gw, args.action_ddic or None,
                        max_depth=args.max_depth, verbose=args.verbose)
    resolver.load_registry(doc)
    params = build_param_list(doc, funcname, resolver)

    if not params:
        print(f"no parameters returned for {funcname}. "
              f"Run again with --dump and check the table key names at the top "
              f"of this script.", file=sys.stderr)

    docs_md = ""
    fm_title = ""
    if args.docs:
        reader = DocReader(gw, args.action_docu or None,
                           langu=args.docs_lang or args.language,
                           verbose=args.verbose)
        fm_title, fm_body = reader.function_doc(funcname)
        param_docs = {p["name"]: reader.parameter_doc(funcname, p["name"]) for p in params}
        docs_md = render_docs(funcname, fm_title, fm_body, params, param_docs)
        if not fm_body and not any(param_docs.values()):
            print(f"no documentation found for {funcname} in language "
                  f"'{args.docs_lang or args.language}'. SAP FMs are often documented "
                  f"in EN only, custom FMs frequently not at all.", file=sys.stderr)

    tree = render_tree(funcname, params, resolver.unresolved, fm_title)
    req = sample_payload(params, "ICT", skip_optional=args.mandatory_only)
    res = sample_payload(params, "ECT")

    os.makedirs(args.outdir, exist_ok=True)
    base = os.path.join(args.outdir, funcname)
    outputs = [(f"{base}.structure.txt", tree),
               (f"{base}.request.json", json.dumps(req, indent=2, ensure_ascii=False)),
               (f"{base}.response.json", json.dumps(res, indent=2, ensure_ascii=False))]
    if args.docs:
        outputs.append((f"{base}.docs.md", docs_md))

    written = []
    for name, content in outputs:
        with open(name, "w", encoding="utf-8") as fh:
            fh.write(content + "\n")
        written.append(name)
    if args.dump:
        name = f"{base}.raw.json"
        with open(name, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        written.append(name)

    if args.print_what in ("all", "tree"):
        print(tree)
    if args.print_what in ("all", "request"):
        print("--- request sample ---")
        print(json.dumps(req, indent=2, ensure_ascii=False))
    if args.print_what in ("all", "response"):
        print("--- response shape ---")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    if args.docs and args.print_what in ("all", "docs"):
        print("--- documentation ---")
        print(docs_md)

    print("\nwritten: " + ", ".join(written), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

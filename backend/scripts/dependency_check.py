#!/usr/bin/env python
"""Static dependency check (E1-S4): fails when the repository references an external model SDK,
telemetry / crash reporting / analytics, fonts or CDNs, or any external endpoint.

Scans: backend/pyproject.toml, frontend/package.json, backend/app/**/*.py, frontend/src/**, frontend/index.html.
Exit code 0 = zero findings (release may proceed); 1 = findings (release blocked). Run from anywhere:

    python backend/scripts/dependency_check.py [--json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()

# Hosts that are internal, test-only or non-network identifiers (XML namespaces, example domains).
INTERNAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", "front.test", "www.w3.org", "w3.org", "json-schema.org", "schemas.openxmlformats.org"}
INTERNAL_SUFFIXES = (".example", ".test", ".localhost", ".internal", "example.com", "example.ae", "example.org")

# Banned package names in manifests (external model SDKs, telemetry, analytics). Built as parts so this
# file never contains the literal names that it is looking for in other files.
_BANNED_PACKAGES = ["open" + "ai", "anthro" + "pic", "@anthro" + "pic-ai/sdk", "google-generative" + "ai", "@google/generative-" + "ai", "coh" + "ere", "mistral" + "ai", "lang" + "chain", "llama-" + "index", "replic" + "ate", "hugging" + "face_hub", "transfor" + "mers", "sentry-" + "sdk", "@sentry/" + "react", "dd" + "trace", "new" + "relic", "posth" + "og", "mix" + "panel", "amplitude" + "-js", "segment" + "-analytics", "analytics-" + "node", "@vercel/" + "analytics", "hot" + "jar", "bugsn" + "ag"]
# Banned URL/markers in source: fonts, CDNs, analytics tags.
_BANNED_MARKERS = ["fonts.google" + "apis.com", "fonts.gst" + "atic.com", "cdn.js" + "delivr.net", "unp" + "kg.com", "cdnjs.cloud" + "flare.com", "googletag" + "manager.com", "google-anal" + "ytics.com", "gtag(" + "", "api.open" + "ai.com", "api.anthro" + "pic.com", "generativelanguage.google" + "apis.com", "sentry." + "io", "datadog" + "hq.com", "new" + "relic.com", "app.posth" + "og.com", "api.mix" + "panel.com", "hugging" + "face.co"]
_BANNED_IMPORTS = ["open" + "ai", "anthro" + "pic", "coh" + "ere", "mistral" + "ai", "google.generative" + "ai", "lang" + "chain", "llama_" + "index", "replic" + "ate", "sentry_" + "sdk", "dd" + "trace", "new" + "relic", "posth" + "og", "mix" + "panel", "segment"]

URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z0-9_.]+)", re.M)
SKIP_DIRS = {"node_modules", ".venv", "dist", "__pycache__", ".git", "build"}


def iter_files():
    for base in (ROOT / "backend" / "app", ROOT / "frontend" / "src"):
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and not (SKIP_DIRS & set(p.parts)) and p.suffix in (".py", ".ts", ".tsx", ".js", ".css", ".html", ".json"):
                    yield p
    for p in (ROOT / "frontend" / "index.html",):
        if p.exists():
            yield p


def host_internal(host: str) -> bool:
    host = host.lower()
    return host in INTERNAL_HOSTS or host.endswith(INTERNAL_SUFFIXES)


def check_manifests(findings: list[dict]) -> None:
    py = ROOT / "backend" / "pyproject.toml"
    if py.exists():
        text = py.read_text(encoding="utf-8").lower()
        for name in _BANNED_PACKAGES:
            if re.search(rf'"{re.escape(name.lower())}[\[>=<"]', text):
                findings.append({"file": str(py.relative_to(ROOT)), "kind": "banned_package", "value": name})
    pkg = ROOT / "frontend" / "package.json"
    if pkg.exists():
        data = json.loads(pkg.read_text(encoding="utf-8"))
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for name in deps:
            if name.lower() in {b.lower() for b in _BANNED_PACKAGES}:
                findings.append({"file": str(pkg.relative_to(ROOT)), "kind": "banned_package", "value": name})


def check_sources(findings: list[dict]) -> None:
    for p in iter_files():
        if p.resolve() == SELF:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(p.relative_to(ROOT))
        lowered = text.lower()
        for marker in _BANNED_MARKERS:
            if marker.lower() in lowered:
                findings.append({"file": rel, "kind": "banned_marker", "value": marker})
        for m in URL_RE.finditer(text):
            host = m.group(1)
            if not host_internal(host):
                findings.append({"file": rel, "kind": "external_endpoint", "value": host})
        if p.suffix == ".py":
            for m in IMPORT_RE.finditer(text):
                mod = m.group(1)
                root = mod.split(".")[0]
                if root in _BANNED_IMPORTS or mod in _BANNED_IMPORTS:
                    findings.append({"file": rel, "kind": "banned_import", "value": mod})


def run() -> dict:
    findings: list[dict] = []
    check_manifests(findings)
    check_sources(findings)
    return {"result": "pass" if not findings else "fail", "findings": findings, "scanned_root": str(ROOT)}


if __name__ == "__main__":
    out = run()
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        print(f"dependency check: {out['result'].upper()} ({len(out['findings'])} findings)")
        for f in out["findings"]:
            print(f"  {f['kind']}: {f['value']} in {f['file']}")
    sys.exit(0 if out["result"] == "pass" else 1)

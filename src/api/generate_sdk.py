#!/usr/bin/env python3
"""Generate a JavaScript SDK from the FastAPI OpenAPI schema.

Builds a lightweight FastAPI app from the routers (matching main.py's
router configuration) to extract the OpenAPI spec without needing
scheduler or ingestion dependencies.

Usage:
    python generate_sdk.py          # write static/js/sdk.js
    python generate_sdk.py --check  # exit 1 if sdk.js is stale
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def build_app():
    from fastapi import FastAPI
    from routers.admin import admin_router
    from routers.auth import auth_router
    from routers.feed import feed_router
    from routers.source_template import source_template_router
    from routers.source import source_router
    from routers.source_analyze import source_analyze_router
    from routers.bulk_import import bulk_import_router
    from routers.item import item_router
    from routers.list import list_router
    from routers.stats import stats_router

    app = FastAPI()
    app.include_router(admin_router, tags=["Admin"])
    app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
    app.include_router(feed_router, prefix="/feed", tags=["Feeds"])
    app.include_router(
        source_template_router, prefix="/source_template", tags=["Source Templates"]
    )
    app.include_router(source_router, prefix="/source", tags=["Sources"])
    app.include_router(
        source_analyze_router, prefix="/source_analyze", tags=["Source Analysis"]
    )
    app.include_router(bulk_import_router, prefix="/import", tags=["Bulk Import"])
    app.include_router(item_router, prefix="/item", tags=["Items"])
    app.include_router(list_router, prefix="/list", tags=["Lists"])
    app.include_router(stats_router, prefix="/stats", tags=["Stats"])
    return app


def method_name_from_path(path, http_method):
    parts = [p for p in path.strip("/").split("/") if not p.startswith("{")]
    tokens = [t for t in re.split(r"[_\-]+", "_".join(parts)) if t]
    if not tokens:
        return http_method
    return tokens[0].lower() + "".join(t.capitalize() for t in tokens[1:])


def generate_sdk(spec):
    lines = [
        "// Auto-generated from OpenAPI spec — do not edit by hand.",
        "// Regenerate: cd src/api && python generate_sdk.py",
        "",
        "class AggySDK {",
        "  constructor(baseUrl = '') {",
        "    this.baseUrl = baseUrl;",
        "    this.token = null;",
        "  }",
        "",
        "  setToken(token) {",
        "    this.token = token;",
        "  }",
        "",
        "  async _request(method, path, { query, body, form } = {}) {",
        "    const headers = {};",
        "    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;",
        "",
        "    let url = this.baseUrl + path;",
        "    if (query) {",
        "      const p = new URLSearchParams();",
        "      for (const [k, v] of Object.entries(query)) {",
        "        if (v != null) p.append(k, String(v));",
        "      }",
        "      const qs = p.toString();",
        "      if (qs) url += '?' + qs;",
        "    }",
        "",
        "    const opts = { method, headers };",
        "    if (form) {",
        "      opts.body = new URLSearchParams(form);",
        "      headers['Content-Type'] = 'application/x-www-form-urlencoded';",
        "    } else if (body) {",
        "      opts.body = JSON.stringify(body);",
        "      headers['Content-Type'] = 'application/json';",
        "    }",
        "",
        "    const resp = await fetch(url, opts);",
        "    if (!resp.ok) {",
        "      if (resp.status === 401) this.token = null;",
        "      const err = await resp.json().catch(() => ({}));",
        "      throw new Error(err.detail || `Request failed (${resp.status})`);",
        "    }",
        "    const text = await resp.text();",
        "    if (!text) return null;",
        "    return JSON.parse(text);",
        "  }",
    ]

    paths = spec.get("paths", {})
    for path in sorted(paths.keys()):
        operations = paths[path]
        for http_method in ("get", "post", "put", "patch", "delete"):
            if http_method not in operations:
                continue
            op = operations[http_method]
            name = method_name_from_path(path, http_method)
            summary = op.get("summary", "")

            params = op.get("parameters", [])
            query_params = [p for p in params if p.get("in") == "query"]
            path_params = [p for p in params if p.get("in") == "path"]

            req_body = op.get("requestBody", {})
            body_content = req_body.get("content", {})
            has_json = "application/json" in body_content
            has_form = "application/x-www-form-urlencoded" in body_content

            js_path = path
            for p in path_params:
                js_path = js_path.replace("{" + p["name"] + "}", "${" + p["name"] + "}")
            uses_template = "${" in js_path
            path_expr = f"`{js_path}`" if uses_template else json.dumps(js_path)

            sig = []
            for p in path_params:
                sig.append(p["name"])
            for p in query_params:
                sig.append(p["name"])
            if has_json:
                sig.append("body")
            if has_form:
                sig.append("formData")

            opts = []
            if query_params:
                qp = ", ".join(p["name"] for p in query_params)
                opts.append(f"query: {{ {qp} }}")
            if has_json:
                opts.append("body")
            if has_form:
                opts.append("form: formData")
            opts_str = ""
            if opts:
                opts_str = ", { " + ", ".join(opts) + " }"

            lines.append("")
            if summary:
                lines.append(f"  /** {summary} */")
            if sig:
                lines.append(f"  async {name}({{ {', '.join(sig)} }}) {{")
            else:
                lines.append(f"  async {name}() {{")
            lines.append(
                f"    return this._request({json.dumps(http_method.upper())}, "
                f"{path_expr}{opts_str});"
            )
            lines.append("  }")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main():
    app = build_app()
    spec = app.openapi()
    sdk = generate_sdk(spec)

    out = Path(__file__).resolve().parent / "static" / "js" / "sdk.js"

    if "--check" in sys.argv:
        current = out.read_text() if out.exists() else ""
        if current != sdk:
            print("ERROR: sdk.js is out of date.")
            print("Run 'cd src/api && python generate_sdk.py' and commit the result.")
            sys.exit(1)
        print("sdk.js is up to date.")
    else:
        out.write_text(sdk)
        print(f"Generated {out}")


if __name__ == "__main__":
    main()

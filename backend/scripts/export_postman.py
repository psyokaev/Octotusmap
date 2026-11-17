"""Xuất collection Postman v2.1 từ OpenAPI của ứng dụng. Chạy: python scripts/export_postman.py"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path(__file__).resolve().parents[2] / "docs" / "postman" / "OctotusMap.postman_collection.json"
LOGIN_PATH = "/api/v1/auth/login"
LOGIN_TEST = [
    "const j = pm.response.json();",
    "pm.test('Đăng nhập thành công', () => pm.response.to.have.status(200));",
    "pm.collectionVariables.set('token', j.access_token);",
]


def example(schema: dict, spec: dict, name: str = "", depth: int = 0):
    """Giá trị mẫu từ JSON Schema; trường mật khẩu luôn là biến Postman, không bao giờ là giá trị thật."""
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    if "anyOf" in schema:
        return example(next((s for s in schema["anyOf"] if s.get("type") != "null"), {}), spec, name, depth)
    if "default" in schema:
        return schema["default"]
    if "password" in name.lower():
        return "{{password}}"
    t = schema.get("type")
    if t == "object" and depth < 4:
        return {k: example(v, spec, k, depth + 1) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [example(schema.get("items", {}), spec, name, depth + 1)] if depth < 4 else []
    if "enum" in schema:
        return schema["enum"][0]
    return {"string": "", "integer": 0, "number": 0, "boolean": False}.get(t)


def build(spec: dict) -> dict:
    folders: dict[str, list] = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            segs = [re.sub(r"\{(\w+)\}", r":\1", s) for s in path.strip("/").split("/")]
            params = op.get("parameters", [])
            req = {
                "method": method.upper(),
                "header": [],
                "url": {
                    "raw": "{{baseUrl}}" + re.sub(r"\{(\w+)\}", r":\1", path),
                    "host": ["{{baseUrl}}"], "path": segs,
                    "query": [{"key": p["name"], "value": "", "disabled": True} for p in params if p["in"] == "query"],
                    "variable": [{"key": p["name"], "value": ""} for p in params if p["in"] == "path"],
                },
                "description": op.get("description") or op.get("summary", ""),
            }
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if body:
                req["header"].append({"key": "Content-Type", "value": "application/json"})
                req["body"] = {"mode": "raw", "raw":
                               json.dumps(example(body["schema"], spec), ensure_ascii=False, indent=2),
                               "options": {"raw": {"language": "json"}}}
            item = {"name": f"{method.upper()} {path}", "request": req, "response": []}
            if path == LOGIN_PATH:
                req["body"]["raw"] = json.dumps({"username": "{{username}}", "password": "{{password}}"}, indent=2)
                req["auth"] = {"type": "noauth"}
                item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": LOGIN_TEST}}]
            folders.setdefault((op.get("tags") or ["Khác"])[0], []).append(item)
    return {
        "info": {"name": "OctotusMap API", "description": "Sinh từ OpenAPI bởi scripts/export_postman.py. "
                 "Đặt username/password trong môi trường rồi chạy 'POST /api/v1/auth/login' để lấy token.",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "variable": [{"key": "baseUrl", "value": "http://127.0.0.1:8000"}, {"key": "token", "value": ""},
                     {"key": "username", "value": ""}, {"key": "password", "value": ""}],
        "item": [{"name": t, "item": items} for t, items in sorted(folders.items())],
    }


def main() -> None:
    from app.main import app

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(app.openapi()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {OUT}")


if __name__ == "__main__":
    main()

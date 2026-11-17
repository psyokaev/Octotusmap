import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from export_postman import build  # noqa: E402

from app.main import app  # noqa: E402


def _requests(items):
    for i in items:
        yield from _requests(i["item"]) if "item" in i else [i]


def test_collection_covers_openapi_without_secrets():
    spec = app.openapi()
    col = json.loads(json.dumps(build(spec)))
    reqs = list(_requests(col["item"]))
    raws = {(r["request"]["method"], r["request"]["url"]["raw"]) for r in reqs}
    for path, ops in spec["paths"].items():
        for m in ops:
            assert (m.upper(), "{{baseUrl}}" + re.sub(r"\{(\w+)\}", r":\1", path)) in raws
    assert {v["key"] for v in col["variable"]} >= {"baseUrl", "token"}
    assert col["auth"]["bearer"][0]["value"] == "{{token}}"
    login = next(r for r in reqs if r["request"]["url"]["raw"].endswith("/auth/login"))
    assert "collectionVariables.set('token'" in "".join(login["event"][0]["script"]["exec"])
    for r in reqs:
        for m in re.finditer(r'"\w*password\w*":\s*"([^"]*)"', r["request"].get("body", {}).get("raw", ""), re.I):
            assert m.group(1).startswith("{{"), r["name"]

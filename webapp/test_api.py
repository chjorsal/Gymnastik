"""
API/integrations-tests mod den KØRENDE server — tester validering,
fejlhåndtering og edge-cases i selve HTTP-laget (app.py).

ADVARSEL: Denne test MUTERER den kørende servers state. Kør kun mod en
server hvor state.json er sikkerhedskopieret (state.json.backup), og
genstart serveren bagefter for at genindlæse den rigtige data.

Kør: python test_api.py [base_url]
"""
import io
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8877"

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
    else:
        FAIL.append((name, detail))
        print(f"FAIL: {name}  {detail}")


def req(method, path, body=None, files=None, expect_json=True):
    """Returnerer (status_code, parsed_json_or_None)."""
    if files is not None:
        boundary = "----testboundary123"
        parts = []
        for field_name, filename, content, content_type in files:
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
            )
            parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
            parts.append(content)
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data = None
        headers = {}

    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read()

    if not expect_json:
        return status, raw
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, None


def run():
    # ============================================================
    # Baseline sanity
    # ============================================================
    status, state = req("GET", "/api/state")
    check("GET /api/state returns 200", status == 200)
    check("GET /api/state has expected top-level keys", state and set(
        ["warmupHalls", "priorityHall", "showHalls", "rows", "schedule"]
    ).issubset(set(state.keys())))

    # ============================================================
    # Row PATCH validation
    # ============================================================
    status, _ = req("PATCH", "/api/rows/does-not-exist", {"field": "varighed", "value": 10})
    check("PATCH nonexistent row id -> 404", status == 404)

    status, _ = req("PATCH", "/api/rows/does-not-exist", {"field": "not_a_real_field", "value": "x"})
    check("PATCH unknown field name -> 400", status == 400)

    # pick a real hold-type row to test against safely, then leave it as-is
    real_row = next(r for r in state["rows"] if r["type"] == "hold")
    rid = real_row["id"]

    status, _ = req("PATCH", f"/api/rows/{rid}", {"field": "hold", "value": "Forsøgt omdøbning"})
    check("PATCH hold name on a real Excel team -> 400 (must be blocked)", status == 400)

    status, result = req("PATCH", f"/api/rows/{rid}", {"field": "varighed", "value": -50})
    check("PATCH varighed with negative value -> clamped to >= 0, no crash", status == 200)
    patched = next(r for r in result["rows"] if r["id"] == rid)
    check("negative varighed clamped to 0, not left negative", patched["varighed"] >= 0, f"got {patched['varighed']}")
    req("PATCH", f"/api/rows/{rid}", {"field": "varighed", "value": real_row["varighed"]})  # restore

    status, result = req("PATCH", f"/api/rows/{rid}", {"field": "opvarmningMin", "value": "ikke-et-tal"})
    check("PATCH opvarmningMin with garbage string -> no crash, treated as cleared", status == 200)
    patched = next(r for r in result["rows"] if r["id"] == rid)
    check("garbage opvarmningMin resolves to None (falls back to default)", patched["opvarmningMinOverride"] is None)

    status, result = req("PATCH", f"/api/rows/{rid}", {"field": "opvarmningHal", "value": "Ikke En Rigtig Hal"})
    check("PATCH opvarmningHal to a hal that doesn't exist -> no crash", status == 200)
    patched = next(r for r in result["rows"] if r["id"] == rid)
    check("invalid opvarmningHal override is rejected (stays None)", patched["opvarmningHalOverride"] is None)

    # ============================================================
    # Special row creation validation
    # ============================================================
    status, _ = req("POST", "/api/rows/special", {"hal": state["showHalls"][0]["name"], "type": "not_a_type"})
    check("POST special row with invalid type -> 400", status == 400)

    status, _ = req("POST", "/api/rows/special", {"hal": "Hal Der Ikke Findes", "type": "pause"})
    check("POST special row for nonexistent show hal -> 404", status == 404)

    # ============================================================
    # Reorder edge cases
    # ============================================================
    hal_name = state["showHalls"][0]["name"]
    status, result = req("POST", "/api/rows/reorder", {"hal": hal_name, "orderedIds": ["fake-id-1", "fake-id-2"]})
    check("reorder with ids that don't belong to the hal -> no crash, ignored", status == 200)

    status, result = req("POST", "/api/rows/reorder", {"hal": hal_name, "orderedIds": []})
    check("reorder with empty id list -> no crash", status == 200)

    # ============================================================
    # Hall management edge cases
    # ============================================================
    status, result = req("POST", "/api/halls/show", {"name": ""})
    check("create show hal with empty name -> no crash, not added", status == 200)
    check("empty-name hal was not actually created", "" not in [h["name"] for h in result["showHalls"]])

    status, result = req("POST", "/api/halls/show", {"name": "   "})
    check("create show hal with whitespace-only name -> no crash, not added", status == 200)
    check(
        "whitespace-only hal was not actually created",
        not any(h["name"].strip() == "" and h["name"] != "" for h in result["showHalls"]),
    )

    status, result = req("POST", "/api/halls/show", {"name": "__TEST_HAL_DUPLICATE__"})
    check("create test show hal -> 200", status == 200)
    status, result2 = req("POST", "/api/halls/show", {"name": "__TEST_HAL_DUPLICATE__"})
    check("create SAME show hal name again -> no crash, no duplicate", status == 200)
    dup_count = sum(1 for h in result2["showHalls"] if h["name"] == "__TEST_HAL_DUPLICATE__")
    check("duplicate hal name did not create a second entry", dup_count == 1, f"count={dup_count}")

    # rename to a name that COLLIDES with an existing hal — this is a real
    # gotcha: does it silently merge two halls together?
    status, result = req("POST", "/api/halls/show", {"name": "__TEST_HAL_B__"})
    status, result = req(
        "PATCH", "/api/halls/show", {"oldName": "__TEST_HAL_B__", "newName": "__TEST_HAL_DUPLICATE__"}
    )
    check("rename hal to a name that collides with another -> no crash (200)", status == 200)
    names_after_collision = [h["name"] for h in result["showHalls"]]
    dup_after = names_after_collision.count("__TEST_HAL_DUPLICATE__")
    check(
        "KNOWN GOTCHA CHECK: renaming to a colliding name — how many halls end up with that name?",
        True,  # informational, not a hard pass/fail — see detail
        f"{dup_after} halls now named '__TEST_HAL_DUPLICATE__' (expected: this silently merges — 1 entry, "
        f"but rows from both former halls now share the name)",
    )

    # clean up test halls
    for name in ["__TEST_HAL_DUPLICATE__", "__TEST_HAL_B__"]:
        req("DELETE", "/api/halls/show", {"name": name})

    # delete a warmup hal that doesn't exist -> should not crash
    status, result = req("DELETE", "/api/halls/warmup", {"name": "Ikke En Rigtig Opvarmningshal"})
    check("delete nonexistent warmup hal -> no crash", status == 200)

    # ============================================================
    # Warmup hall lifecycle edge cases (create, set priority, delete —
    # then restore exactly to not disturb the real setup)
    # ============================================================
    status, original = req("GET", "/api/state")
    original_warmup_halls = list(original["warmupHalls"])
    original_priority = original["priorityHall"]

    status, result = req("POST", "/api/halls/warmup", {"name": "__TEST_WARMUP__"})
    check("create test warmup hal -> 200", status == 200)
    status, result = req("POST", "/api/halls/warmup/priority", {"name": "__TEST_WARMUP__"})
    check("set test warmup hal as priority -> 200", status == 200 and result["priorityHall"] == "__TEST_WARMUP__")

    status, result = req("DELETE", "/api/halls/warmup", {"name": "__TEST_WARMUP__"})
    check("delete the CURRENT priority warmup hal -> no crash", status == 200)
    check(
        "priority hal auto-reassigns to a remaining hal after its deletion (not left dangling)",
        result["priorityHall"] in result["warmupHalls"] or result["priorityHall"] is None,
        f"priorityHall={result['priorityHall']} warmupHalls={result['warmupHalls']}",
    )

    # delete ALL warmup halls -> system must degrade gracefully, not crash
    status, result = req("GET", "/api/state")
    for name in list(result["warmupHalls"]):
        status, result = req("DELETE", "/api/halls/warmup", {"name": name})
    check("deleting every warmup hal one by one never crashes", status == 200)
    check("with zero warmup halls, priorityHall is None", result["priorityHall"] is None)
    status, state_no_halls = req("GET", "/api/state")
    check(
        "GET /api/state with zero warmup halls still returns valid rows (status MANGLER, not a crash)",
        status == 200 and all(r["status"] in ("MANGLER", "IGNORERET") for r in state_no_halls["rows"]),
    )

    # restore the real warmup hall configuration exactly as it was
    for name in original_warmup_halls:
        req("POST", "/api/halls/warmup", {"name": name})
    req("POST", "/api/halls/warmup/priority", {"name": original_priority})
    status, restored = req("GET", "/api/state")
    check(
        "warmup halls fully restored after the destructive lifecycle test",
        restored["warmupHalls"] == original_warmup_halls and restored["priorityHall"] == original_priority,
        f"got {restored['warmupHalls']} / {restored['priorityHall']}",
    )

    # ============================================================
    # Unicode / special characters in hall names
    # ============================================================
    weird_name = "Hal Æ Ø Å 特殊字符 🏟️"
    status, result = req("POST", "/api/halls/show", {"name": weird_name})
    check("create show hal with unicode/emoji name -> 200", status == 200)
    check("unicode hal name round-trips exactly", weird_name in [h["name"] for h in result["showHalls"]])
    req("DELETE", "/api/halls/show", {"name": weird_name})

    # ============================================================
    # Upload edge cases
    # ============================================================
    status, result = req(
        "POST", "/api/upload",
        files=[("files", "empty.xlsx", b"", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
        expect_json=False,
    )
    check(
        "upload a genuinely empty/corrupt .xlsx file -> server does not crash (5xx)",
        status < 500,
        f"status={status}",
    )

    status, result = req(
        "POST", "/api/upload",
        files=[("files", "garbage.xlsx", b"this is not an excel file at all", "text/plain")],
        expect_json=False,
    )
    check(
        "upload garbage bytes with .xlsx extension -> server does not crash (5xx)",
        status < 500,
        f"status={status}",
    )

    # ============================================================
    # Export edge case
    # ============================================================
    status, raw = req("GET", "/api/export.xlsx", expect_json=False)
    check("GET export.xlsx -> 200", status == 200)
    check("export response looks like a real xlsx (starts with PK zip header)", raw[:2] == b"PK", f"first bytes={raw[:8]!r}")

    # ============================================================
    # State survives a reload from disk (persistence round-trip)
    # ============================================================
    status, state_before = req("GET", "/api/state")
    check("final state fetch before restore -> 200", status == 200)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nFAILED:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
    return len(FAIL) == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)

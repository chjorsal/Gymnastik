"""
Røgtest af serverudgaven (app.py). Starter sin egen server på en ledig port
med en midlertidig STATE_FILE — rører aldrig den rigtige state.json.

Kør: python test_api.py
"""
import json
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from testkit import check, excel_bytes, start_server, summary



def run():
    tmp = tempfile.mkdtemp()
    server, url = start_server(tmp)
    base = url.rstrip("/")

    def req(method, path, body=None, raw=None, headers=None, want_headers=False):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = headers or ({"Content-Type": "application/json"} if body is not None else {})
        r = urllib.request.Request(base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                result = (resp.status, resp.read())
                return result + (resp.headers,) if want_headers else result
        except urllib.error.HTTPError as e:
            return (e.code, e.read(), e.headers) if want_headers else (e.code, e.read())

    try:
        status, body = req("GET", "/api/state")
        state = json.loads(body)
        check("GET /api/state -> 200 with frontend keys", status == 200 and
              set(state) == {"warmupHalls", "priorityHall", "showHalls", "rows", "schedule"})
        check("fresh server has no warm-up halls", state["warmupHalls"] == [])
        check("fresh server starts with the show hall 'Hal 1'",
              state["showHalls"] == [{"name": "Hal 1", "startTime": "09:00"}], state["showHalls"])

        status, body = req("POST", "/api/halls/warmup", {"name": "Varm 1"})
        check("create warm-up hall", status == 200 and json.loads(body)["warmupHalls"] == ["Varm 1"])
        req("POST", "/api/halls/show", {"name": "Sal A"})

        status, body = req("POST", "/api/halls/show/starttime", {"name": "Sal A", "startTime": "abc"})
        check("invalid start time -> 400 with error", status == 400 and "gyldigt klokkeslæt" in json.loads(body)["error"])

        boundary = "----t"
        parts = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"show_hal\"\r\n\r\nSal A\r\n"
                 f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"dag.xlsx\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + excel_bytes(["Hold 1", "Hold 2"]) + f"\r\n--{boundary}--\r\n".encode()
        status, body = req("POST", "/api/upload", raw=parts,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        rows = json.loads(body)["rows"] if status == 200 else []
        check("upload puts teams in the chosen hall", status == 200 and [r["opvisningHal"] for r in rows] == ["Sal A", "Sal A"],
              body[:200])

        bad = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"x.xlsx\"\r\n\r\n"
               f"ikke excel\r\n--{boundary}--\r\n").encode()
        status, body = req("POST", "/api/upload", raw=bad,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        check("garbage upload -> 400 with error", status == 400 and "x.xlsx" in json.loads(body)["error"])

        def multipart(parts):
            body = b""
            for name, filename, data in parts:
                disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
                body += f"--{boundary}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + data + b"\r\n"
            return body + f"--{boundary}--\r\n".encode()

        req("POST", "/api/halls/show", {"name": "Sal B"})
        raw = multipart([("files", "a.xlsx", excel_bytes(["A1"])), ("halls", None, "Sal A".encode()),
                         ("files", "b.xlsx", excel_bytes(["B1"])), ("halls", None, "Sal B".encode())])
        status, body = req("POST", "/api/upload-halls", raw=raw,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        rows = json.loads(body)["rows"] if status == 200 else []
        check("upload-halls puts each file in its own hall", status == 200
              and [(r["hold"], r["opvisningHal"]) for r in rows if r["hold"] in ("A1", "B1")]
              == [("A1", "Sal A"), ("B1", "Sal B")], body[:200])
        raw = multipart([("files", "a.xlsx", excel_bytes(["A2"])), ("halls", None, "Sal A".encode()),
                         ("files", "c.xlsx", excel_bytes(["C1"]))])
        status, body = req("POST", "/api/upload-halls", raw=raw,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        check("upload-halls with a file without a hall -> 400", status == 400, body[:200])

        status, _ = req("PATCH", "/api/rows/findes-ikke", {"field": "varighed", "value": 1})
        check("patch missing row -> 404", status == 404)

        status, body, headers = req("GET", "/api/export.xlsx", want_headers=True)
        check("export -> 200 xlsx with the default file name", status == 200 and body[:2] == b"PK"
              and 'filename="opvisning_med_opvarmning.xlsx"' in headers["Content-Disposition"],
              headers["Content-Disposition"])
        name = urllib.parse.quote("Lørdag: Arena/Hal2.xlsx")
        status, body, headers = req("GET", f"/api/export.xlsx?name={name}", want_headers=True)
        disp = headers["Content-Disposition"]
        check("export uses the cleaned user name, æøå kept via filename*", status == 200
              and "filename*=UTF-8''L%C3%B8rdag%20Arena%20Hal2.xlsx" in disp
              and 'filename="L_rdag Arena Hal2.xlsx"' in disp, disp)

        saved = json.loads((Path(tmp) / "state.json").read_text(encoding="utf-8"))
        check("state is saved to STATE_FILE", len(saved["raw_rows"]) == 4)
    finally:
        server.terminate()
        server.wait(timeout=10)

    return summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

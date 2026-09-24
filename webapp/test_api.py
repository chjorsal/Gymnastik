"""
Røgtest af serverudgaven (app.py). Starter sin egen server på en ledig port
med en midlertidig STATE_FILE — rører aldrig den rigtige state.json.

Kør: python test_api.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS.append(name) if condition else FAIL.append((name, detail)))
    if not condition:
        print(f"FAIL: {name}  {detail}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def excel_bytes():
    df = pd.DataFrame({"Tid": ["09:00", ""], "Varighed": [10, 10], "Holdnavn": ["Hold 1", "Hold 2"],
                       "Antal deltagere": [20, 20], "Alder": ["voksen", "voksen"]})
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def run():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, STATE_FILE=str(Path(tmp) / "state.json"), PORT=str(port))
    server = subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def req(method, path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = headers or ({"Content-Type": "application/json"} if body is not None else {})
        r = urllib.request.Request(base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        for _ in range(60):
            try:
                if req("GET", "/api/state")[0] == 200:
                    break
            except OSError:
                time.sleep(0.25)

        status, body = req("GET", "/api/state")
        state = json.loads(body)
        check("GET /api/state -> 200 with frontend keys", status == 200 and
              set(state) == {"warmupHalls", "priorityHall", "showHalls", "rows", "schedule"})
        check("fresh server has no warm-up halls", state["warmupHalls"] == [])

        status, body = req("POST", "/api/halls/warmup", {"name": "Varm 1"})
        check("create warm-up hall", status == 200 and json.loads(body)["warmupHalls"] == ["Varm 1"])
        req("POST", "/api/halls/show", {"name": "Sal A"})

        status, body = req("POST", "/api/halls/show/starttime", {"name": "Sal A", "startTime": "abc"})
        check("invalid start time -> 400 with error", status == 400 and "gyldigt klokkeslæt" in json.loads(body)["error"])

        boundary = "----t"
        parts = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"show_hal\"\r\n\r\nSal A\r\n"
                 f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"dag.xlsx\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + excel_bytes() + f"\r\n--{boundary}--\r\n".encode()
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

        status, _ = req("PATCH", "/api/rows/findes-ikke", {"field": "varighed", "value": 1})
        check("patch missing row -> 404", status == 404)

        status, body = req("GET", "/api/export.xlsx")
        check("export -> 200 xlsx", status == 200 and body[:2] == b"PK")

        saved = json.loads((Path(tmp) / "state.json").read_text(encoding="utf-8"))
        check("state is saved to STATE_FILE", len(saved["raw_rows"]) == 2)
    finally:
        server.terminate()
        server.wait(timeout=10)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

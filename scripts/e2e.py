"""Fresh-database end-to-end run through the HTTP API: activate the stand-in, upload all samples, wait, report."""
import json, os, sys, time
import httpx

API = os.getenv("API", "http://localhost:8000")
H = {"Authorization": f"Bearer {os.environ['APP_API_TOKEN']}", "X-User-Role": "supervisor", "X-User-Name": "e2e.runner"}
labels = json.load(open("samples/eval/labels.json"))
c = httpx.Client(base_url=API, headers=H, timeout=60)

integ = c.get("/api/integrations").json()["integrations"][0]
t = c.post(f"/api/integrations/{integ['id']}/test").json()
print("test connection:", t["last_test_ok"], t.get("last_test_message"))
print("activate:", c.post(f"/api/integrations/{integ['id']}/activate").json()["is_active"])

ids = {}
for lab in labels:
    p = f"samples/eval/files/{lab['file']}"
    r = c.post("/api/documents", files=[("files", (lab["file"], open(p, "rb").read()))]).json()["results"][0]
    ids[lab["id"]] = r["claim_id"]
t0 = time.time()
while time.time() - t0 < 300:
    sts = {k: c.get(f"/api/claims/{v}").json()["status"] for k, v in ids.items()}
    if not any(s in ("queued", "processing", "pushing") for s in sts.values()):
        break
    time.sleep(3)
rows = []
for k, v in ids.items():
    d = c.get(f"/api/claims/{v}").json()
    u = d.get("llm_usage") or {}
    rows.append((k, d["status"], d.get("external_claim_number"), [r["code"] for r in d.get("review_reasons") or []],
                 d.get("timings_ms", {}).get("total"), u.get("cost_usd")))
    print(f"{k:34s} {d['status']:13s} {str(d.get('external_claim_number')):14s} {d.get('timings_ms', {}).get('total')}ms ${u.get('cost_usd')} {[r['code'] for r in d.get('review_reasons') or []]}")
print("total cost", round(sum(r[5] or 0 for r in rows), 6), "wall s", round(time.time() - t0, 1))
json.dump({"ids": ids, "rows": rows}, open("logs/e2e_result.json", "w"), indent=1)

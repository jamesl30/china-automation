"""EWS shipping tracker -> Discord. Runs on GitHub Actions cron. Stdlib only."""
import os, json, urllib.request, urllib.error

KEY  = os.environ["TRACKINGMORE_API_KEY"]
HOOK = os.environ["DISCORD_WEBHOOK_URL"]
NUM  = os.environ["TRACKING_NUMBER"]
API  = "https://api.trackingmore.com/v4/trackings"
H    = {"Content-Type": "application/json", "Tracking-Api-Key": KEY}


def call(method, url, body=None, headers=H):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or "{}")  # surfaces "already exists" etc.


# 1. idempotent register (no-op if already tracked)
call("POST", f"{API}/create", {"tracking_number": NUM, "courier_code": "ews"})

# 2. fetch latest status
res = call("GET", f"{API}/get?tracking_numbers={NUM}")
item = (res.get("data") or [{}])[0]
status = item.get("delivery_status", "unknown")
track = (item.get("origin_info") or {}).get("trackinfo") or []
latest = track[0] if track else {}
line = latest.get("tracking_detail", "No checkpoints yet")
when = latest.get("checkpoint_date", "")
where = latest.get("location", "")

# 3. did the latest checkpoint change since last run?
try:
    prev = json.load(open("last_status.json")).get("line")
except Exception:
    prev = None
changed = (line != prev)

# 4. build + send Discord message
emoji = "🟢" if status == "delivered" else "🟡"
banner = "**🔔 UPDATE since last check**\n" if changed and prev else ""
msg = f"{banner}{emoji} **EWS {NUM}** — `{status}`\n{line}\n📍 {where}  🕒 {when}"
call("POST", HOOK, {"content": msg}, headers={"Content-Type": "application/json"})

# 5. persist
json.dump({"line": line}, open("last_status.json", "w"))
print("sent:", msg)

"""EWS shipping tracker -> Discord. Runs on GitHub Actions cron. Stdlib only."""
import os, json, urllib.request, urllib.error

KEY  = os.environ["TRACKINGMORE_API_KEY"]
HOOK = os.environ["DISCORD_WEBHOOK_URL"]
NUM  = os.environ["TRACKING_NUMBER"]
API  = "https://api.trackingmore.com/v4/trackings"
# Discord is behind Cloudflare, which 403s (error 1010) the default Python-urllib UA.
UA   = "ews-tracker/1.0 (+https://github.com)"
H    = {"Content-Type": "application/json", "Tracking-Api-Key": KEY, "User-Agent": UA}


def call(method, url, body=None, headers=H):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return _parse(r.status, r.read())
    except urllib.error.HTTPError as e:
        return _parse(e.code, e.read())  # 4xx/5xx still return a usable dict


def _parse(status, raw):
    text = (raw or b"").decode("utf-8", "replace").strip()
    try:
        out = json.loads(text) if text else {}
    except ValueError:
        out = {"_text": text}  # non-JSON body (HTML/empty error page)
    out["_status"] = status
    return out


# 1. idempotent register (no-op if already tracked)
call("POST", f"{API}/create", {"tracking_number": NUM, "courier_code": "8dt"})

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
dres = call("POST", HOOK, {"content": msg}, headers={"Content-Type": "application/json", "User-Agent": UA})

# Discord webhook returns 204 No Content on success. Anything else = a real error.
if dres.get("_status") != 204:
    raise SystemExit(f"Discord webhook failed: HTTP {dres.get('_status')} {dres}")

# 5. persist (only reached on a successful send)
json.dump({"line": line}, open("last_status.json", "w"))
print("sent:", msg)

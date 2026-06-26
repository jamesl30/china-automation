"""Package trackers -> Discord. Runs on GitHub Actions cron. Stdlib only."""
import os, json, urllib.request, urllib.error

KEY      = os.environ["TRACKINGMORE_API_KEY"]
HOOK     = os.environ["DISCORD_WEBHOOK_URL"]
EWS_NUM  = os.environ["TRACKING_NUMBER"]
GOFO_NUM = os.environ.get("GOFO_TRACKING_NUMBER", "").strip()
API      = "https://api.trackingmore.com/v4/trackings"
GOFO_API = "https://www.gofo.com/us/cnee-api/consignee/track/query"
# Discord is behind Cloudflare, which 403s (error 1010) the default Python-urllib UA.
UA       = "package-tracker/1.0 (+https://github.com)"
H        = {"Content-Type": "application/json", "Tracking-Api-Key": KEY, "User-Agent": UA}
GOFO_H   = {"Content-Type": "application/json", "Accept": "application/json", "lang": "en", "User-Time-Zone": "America/New_York", "User-Agent": UA}


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


def trackingmore_package():
    # idempotent register (no-op if already tracked)
    call("POST", f"{API}/create", {"tracking_number": EWS_NUM, "courier_code": "8dt"})

    res = call("GET", f"{API}/get?tracking_numbers={EWS_NUM}")
    item = (res.get("data") or [{}])[0]
    status = item.get("delivery_status", "unknown")
    track = (item.get("origin_info") or {}).get("trackinfo") or []
    latest = track[0] if track else {}
    return {
        "key": "ews",
        "label": f"EWS {EWS_NUM}",
        "status": status,
        "line": latest.get("tracking_detail", "No checkpoints yet"),
        "when": latest.get("checkpoint_date", ""),
        "where": latest.get("location", ""),
    }


def gofo_package():
    res = call("POST", GOFO_API, {"numberList": [GOFO_NUM]}, headers=GOFO_H)
    item = ((res.get("data") or {}).get("success") or [{}])[0]
    latest = item.get("lastTrackEvent") or ((item.get("trackEventList") or [{}])[0])
    where = ", ".join(x for x in [latest.get("processCity"), latest.get("processProvince")] if x)
    return {
        "key": "gofo",
        "label": f"GOFO {GOFO_NUM}",
        "status": item.get("status", "unknown"),
        "line": latest.get("processContent", res.get("msg") or "No checkpoints yet"),
        "when": latest.get("processDate", ""),
        "where": where or latest.get("processLocation", ""),
    }


def load_previous():
    try:
        data = json.load(open("last_status.json"))
    except Exception:
        return {}
    if "packages" in data:
        return data["packages"]
    if "line" in data:
        return {"ews": {"line": data.get("line")}}
    return data


def status_emoji(status):
    return "🟢" if str(status).lower() == "delivered" else "🟡"


def format_package(pkg, previous):
    prev_line = (previous.get(pkg["key"]) or {}).get("line")
    changed = pkg["line"] != prev_line
    banner = "**🔔 UPDATE since last check**\n" if changed and prev_line else ""
    return f"{banner}{status_emoji(pkg['status'])} **{pkg['label']}** — `{pkg['status']}`\n{pkg['line']}\n📍 {pkg['where']}  🕒 {pkg['when']}"


previous = load_previous()
packages = [trackingmore_package()]
if GOFO_NUM:
    packages.append(gofo_package())

msg = "\n\n".join(format_package(pkg, previous) for pkg in packages)
dres = call("POST", HOOK, {"content": msg}, headers={"Content-Type": "application/json", "User-Agent": UA})

# Discord webhook returns 204 No Content on success. Anything else = a real error.
if dres.get("_status") != 204:
    raise SystemExit(f"Discord webhook failed: HTTP {dres.get('_status')} {dres}")

# persist (only reached on a successful send)
state = {
    "packages": {
        pkg["key"]: {
            "line": pkg["line"],
            "status": pkg["status"],
            "when": pkg["when"],
        }
        for pkg in packages
    }
}
json.dump(state, open("last_status.json", "w"), indent=2, sort_keys=True)
print("sent:", msg)

from flask import Flask, jsonify, send_from_directory
import os
from flask_cors import CORS
from nsepython import nsefetch
import datetime, time

app = Flask(__name__)
CORS(app)  # allow your HTML / GitHub Pages site to call this API

CACHE_SECONDS = 15  # avoids hammering NSE (it rate-limits and blocks)
_cache = {"t": 0, "data": None}


def get_indices():
    rows = nsefetch("https://www.nseindia.com/api/allIndices")["data"]
    by = {r["index"]: r for r in rows}
    return by["NIFTY 50"], by["INDIA VIX"]


def get_option_levels(spot):
    """Max pain, highest Put OI below spot (support), highest Call OI above spot (resistance)."""
    try:
        rec = nsefetch("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY")["records"]
        exp = rec["expiryDates"][0]
        ce, pe = {}, {}
        for r in rec["data"]:
            if r.get("expiryDate") != exp:
                continue
            k = r["strikePrice"]
            ce[k] = (r.get("CE") or {}).get("openInterest", 0)
            pe[k] = (r.get("PE") or {}).get("openInterest", 0)
        strikes = sorted(set(ce) | set(pe))
        pain = lambda s: sum(ce.get(k, 0) * max(0, s - k) + pe.get(k, 0) * max(0, k - s) for k in strikes)
        return {
            "max_pain": min(strikes, key=pain),
            "support": max((k for k in pe if k <= spot), key=pe.get, default=None),
            "resistance": max((k for k in ce if k >= spot), key=ce.get, default=None),
        }
    except Exception as e:
        print("option chain failed:", e)
        return {"max_pain": None, "support": None, "resistance": None}


def get_fii_dii():
    out = {"fii_net": None, "dii_net": None}
    try:
        for r in nsefetch("https://www.nseindia.com/api/fiidiiTradeReact"):
            net = float(str(r["netValue"]).replace(",", ""))
            if "FII" in r["category"].upper():
                out["fii_net"] = net
            elif "DII" in r["category"].upper():
                out["dii_net"] = net
    except Exception as e:
        print("fii/dii failed:", e)
    return out


@app.route("/")
def home():
    # Serves the dashboard from the same folder, so just open http://localhost:5000
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.route("/api/live-data")
def live_data():
    if _cache["data"] and time.time() - _cache["t"] < CACHE_SECONDS:
        return jsonify(_cache["data"])
    try:
        nifty, vix = get_indices()
        spot = float(nifty["last"])
        prev = float(nifty["previousClose"])
        opening = float(nifty.get("open") or 0) or prev  # before 9:15 'open' may be 0
        data = {
            "status": "success",
            "nifty_spot": spot,
            "prev_close": prev,
            "opening_price": opening,
            "spread_pts": round(spot - opening, 2),
            "india_vix": float(vix["last"]),
            "signal_930": "GREEN" if spot >= opening else "RED",
            "timestamp": datetime.datetime.now().strftime("%I:%M:%S %p"),
            **get_option_levels(spot),
            **get_fii_dii(),
        }
        _cache.update(t=time.time(), data=data)
        return jsonify(data)
    except Exception as e:
        # Return a real error instead of fake numbers, so the dashboard shows "Offline"
        return jsonify({"status": "error", "error": str(e)}), 503


if __name__ == "__main__":
    print("Backend running at http://localhost:5000/api/live-data")
    app.run(host="0.0.0.0", port=5000)

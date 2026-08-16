import json
import time
import urllib.parse
import urllib.request

POOL = "data/stock-pool/pool.json"
URL = "https://searchapi.eastmoney.com/api/suggest/get"
TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

HK_HINTS = ("-W", "[HK]", "腾讯控股", "中芯国际", "华虹宏力", "信达生物", "百济神州", "药明生物", "药明合联", "康方生物", "安踏体育", "泡泡玛特", "优必选", "晶泰控股", "建滔积层板", "古茗")


def search(name: str) -> list:
    q = urllib.parse.quote(name)
    url = f"{URL}?input={q}&type=14&token={TOKEN}&count=5"
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("QuotationCodeTable", {}).get("Data", [])
    except Exception:
        return []


def exch_of(r: dict, code: str) -> str:
    if r.get("Classify") == "HK":
        return "HK"
    if code.startswith(("60", "68")):
        return "SH"
    return "SZ"


def main() -> None:
    pool = json.load(open(POOL, encoding="utf-8"))
    matched, unmatched, skipped = [], [], 0
    for s in pool["stocks"]:
        if s.get("code"):
            skipped += 1
            continue
        name = s["name"]
        rows = search(name)
        exact = [r for r in rows if r.get("Name") == name] or rows
        is_hk = any(h in name for h in HK_HINTS)
        pick = None
        for r in exact:
            if is_hk and r.get("Classify") == "HK":
                pick = r
                break
            if not is_hk and r.get("Classify") == "AStock":
                pick = r
                break
        if pick is None and exact:
            pick = exact[0]
        if pick:
            code = pick["Code"]
            s["code"] = code
            s["exchange"] = exch_of(pick, code)
            matched.append((name, code, pick.get("Classify", "")))
        else:
            unmatched.append(name)
        time.sleep(0.05)

    pool["count"] = len(pool["stocks"])
    pool["version"] = "2026-08-15-codes"
    json.dump(pool, open(POOL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"matched: {len(matched)} | unmatched: {len(unmatched)} | skipped(already): {skipped}")
    for m in matched:
        print("  OK ", m)
    print("UNMATCHED:", unmatched)


if __name__ == "__main__":
    main()

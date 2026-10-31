import sys, json
sys.path.insert(0, ".")
import mod_ip
sc = mod_ip.run_scenario()
for i, s in enumerate(sc["steps"], 1):
    r = s.get("result")
    print(i, s["title"], "ok=" + str(s["ok"]), "keys=" + (str(list(r.keys())) if isinstance(r, dict) else type(r).__name__))
    if isinstance(r, dict):
        print("   ", json.dumps({k:r[k] for k in list(r)[:8]}, ensure_ascii=False)[:500])

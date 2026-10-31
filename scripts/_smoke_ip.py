import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import mod_ip

print("CONFIG", mod_ip.config()["module"]["title"], len(mod_ip.config()["shots"]))
print("DURATION", json.dumps(mod_ip.duration_report(), ensure_ascii=False))
man = mod_ip.build_manifest()
print("MANIFEST", man["totalMs"], man["shotCount"], man["master"], man["allAudioFits"], man["assetsOk"], man["warnings"])
cat = mod_ip.asset_catalog()
print("ASSETS", json.dumps(cat["summary"], ensure_ascii=False), [c["ok"] for c in cat["checks"]])
print("VALIDATE", json.dumps(mod_ip.validate_assets(), ensure_ascii=False)[:500])
r = mod_ip.review_text(mod_ip.config()["review"]["samples"]["pass"], "合规文案", "ops")
print("PASS", r["verdict"], r["findings"])
r = mod_ip.review_text(mod_ip.config()["review"]["samples"]["reject"], "违规文案", "ops")
print("REJECT", r["verdict"], [f["rule"] for f in r["findings"]])
d = mod_ip.license_preview({"licensee":"合成样例文化品牌（演示）","purpose":"品牌短片","territory":"中国大陆","term":12}, "finance")
print("LICENSE", d["draftNo"], d["clauseCount"], d["fullText"][:120].replace("\n"," | "))
try:
    mod_ip.review_text("越权测试文案", "越权", "workshop")
except mod_ip.IpError as e:
    print("FORBIDDEN", e.status, e.error, e.message)
try:
    mod_ip.validate_assets(role="admin", simulate_missing_audio=True)
except mod_ip.IpError as e:
    print("MISSING", e.status, e.error, e.message, e.extra.get("simulated"))
sc = mod_ip.run_scenario()
print("SCENARIO", sc["scenario"], sc["summary"])
for s in sc["steps"]:
    print(("OK " if s["ok"] else ("EXP" if s.get("expectError") else "FAIL")), s["title"], s.get("error",""), s.get("message",""))

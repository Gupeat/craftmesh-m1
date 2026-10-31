import sys, json
sys.path.insert(0, ".")
import mod_ip
a = mod_ip.asset_catalog()["assets"]
print(json.dumps(a[:3], ensure_ascii=False, indent=2))
print(json.dumps(a[-3:], ensure_ascii=False, indent=2))

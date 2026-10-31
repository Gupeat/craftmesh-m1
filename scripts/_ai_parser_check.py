import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mod_ai

for ind_id, text in [
    ("woodcraft", "请记录：王女士 wang2@example.com，预算 12 万，黑胡桃餐桌，来自日本"),
    ("woodcraft", "我的邮箱是 chen@example.com，想咨询白蜡木书柜，预算 8 万"),
    ("jewelry", "联系人：李女士，li@example.com，想定制 18K 金婚戒，预算 3 万"),
]:
    ind = mod_ai._industry(ind_id)
    print(ind_id, json.dumps(mod_ai._lead_fields_from_text(text, ind), ensure_ascii=False))

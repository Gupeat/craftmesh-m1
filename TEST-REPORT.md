# CraftMesh 测试与验证记录（ClawHunt #1724 · M1 + M2 + B + C）

最近一次全量实测：2026-10-31 03:20（Asia/Shanghai，UTC+8）
环境：Windows 11 / CPython 3.12.14 / 仅标准库 / SQLite 本地文件
范围：同一仓库、同一 HTTP 服务的四个模块 + 验收驾驶舱
数据：全部为合成、自制或脱敏样例

## 1. 总览

| 项目 | 结果 |
| --- | --- |
| 自动化单测 | Ran 85 tests in 8.0s · OK（85/85） |
| M2 预售与制造协同场景 | 16 步：15 成功 + 1 步预期拒绝（能力不匹配） |
| B 企业 AI 服务层场景 | 17 步：15 成功 + 2 步预期拒绝（越权 / 空值校验） |
| C 文化 IP 短剧管线场景 | 16 步：14 成功 + 2 步预期拒绝（工坊越权 / 缺失素材） |
| 平台验收映射 0)~10) | 11/11 项通过（48/48 检查） |
| 证据包 | data/evidence/packs/ 下最新生成的 evidence-pack-*.md（约 18.3 KB） |
| 浏览器 | Edge 156 headless / CDP，1680 宽，0 未捕获 JS 异常；390 宽移动视口复验五页，scrollWidth=375、无横向溢出 |

复跑命令：

~~~bash
cd clawhunt/1724-demo

# 全量单测（85 个）
python -m unittest discover -s tests -v

# 启动服务（默认 127.0.0.1:8787）
python server.py

# 一条命令验收（探活 + 单测 + 静态检查 + 三套场景）
python verify_all.py

# 浏览器打开验收驾驶舱并一键全量自检 + 导出证据包
# http://127.0.0.1:8787/pages/evidence.html
# 或自动化入口：/pages/evidence.html?autorun=1&export=1
~~~

## 2. 自动化测试组成（85 个）

| 测试文件 | 数量 | 覆盖 |
| --- | --- | --- |
| tests/test_core.py | 21 | 规则引擎 10 条规则 / 3 条硬约束、授权校验、人工规则对照 10/10、报价、订单快照、状态机、权限 |
| tests/test_api.py | 10 | 真实 HTTP 集成：health / bootstrap / check / 创建订单 / 详情 / 状态迁移 / 静态白名单 / 重置 / 源码包下载与目录穿越拦截 |
| tests/test_m2.py | 16 | 报价与定金服务端计算、起订量、成团自动生成工艺单、取消退定金、能力预检 5 项、误派 422、接单/拒单、质检 fail 必填备注、返工上限升级、分账平衡、争议退款台账、角色 403、重置 |
| tests/test_ai.py | 18 | 双行业配置、种子知识 4 篇/12 块、检索引用、行业切换、智能体检索/留资工具轨迹、工作流成功 7 步、失败重试 attempt=2、成功 run 不可重试 409、询盘校验 422、线索阶段 history、三语 SEO 100%、FDE 手册、权限 403、重置、dashboard、17 步场景 |
| tests/test_ip.py | 14 | 双原创角色、6 场 beats、12 分镜、总时长 30-45s、WAV/SRT 存在与格式、播放器 manifest、9 条审核规则、审核留痕、授权 12 条款、6 个衍生 SKU、权限与素材缺失拒绝 |
| tests/test_evidence.py | 6 | 验收配置 11 项 P0–P10、编号与检查类型合法、m1cases 10/3 基线、tests 阈值、场景阈值、证据包 Markdown 结构 |

测试数据库均为独立临时 SQLite，不污染 data/*.db。

## 3. 三套全链路场景（HTTP 实测）

启动服务后：

~~~bash
curl -s -X POST http://127.0.0.1:8787/api/m2/scenario -H "Content-Type: application/json" -d "{\"role\":\"admin\"}"
curl -s -X POST http://127.0.0.1:8787/api/ai/scenario -H "Content-Type: application/json" -d "{\"role\":\"admin\"}"
curl -s -X POST http://127.0.0.1:8787/api/ip/scenario -H "Content-Type: application/json" -d "{\"role\":\"admin\"}"
~~~

结果均为 ok=true：

- M2：16 步，15 成功 + 1 预期拒绝；成团 -> 工艺单 -> 能力预检 -> 派单 -> 接单 -> 开工 -> 质检返工 -> 放行 -> 发货 -> 分账 -> 争议退款全链路。
- B：17 步，15 成功 + 2 预期拒绝；建行业 -> 建文档 -> 检索 -> 智能体工具调用 -> 写 CRM -> 流程成功 -> 失败重试 -> 三语站点/SEO -> 手册 -> 越权/空值拒绝。
- C：16 步，14 成功 + 2 预期拒绝；剧本 -> 12 分镜 -> 时长校验 -> 41 项自制素材 -> 播放器 manifest -> 审核通过/拒绝 -> 授权 12 条款 -> 6 SKU -> 越权/缺失素材拒绝。

## 4. 验收驾驶舱（0)~10) 映射）

页面 /pages/evidence.html 把平台任务书 0)~10) 拆成 11 项 P0–P10，每项列出检查项、执行方式、证据与可复跑命令；一键自检会：

1. 服务端静态检查（文件存在/大小、源码关键字、M1 人工规则 10/10、unittest 85 个）；
2. 浏览器侧模块探测（M1/M2/B/C 的 config、health 与 HTTP 检查）；
3. 依次执行三套全链路场景（49 步）；
4. 汇总为 11 项结论并写入运行记录；
5. 导出 Markdown 证据包（含环境、manifest、SHA-256、逐项证据、场景步骤）。

最近一次结果：11/11 项通过，48/48 检查通过，49 个场景步骤；证据包写入 data/evidence/packs/（文件名带运行编号，页面“证据包”区可直接下载）。

## 5. 浏览器验证（Edge headless / CDP）

已验证页面（均从 /api/* 实时取数，无静态假数据）：

- / ：M1 工作台、KPI、判定摘要、授权快照、报价、订单列表
- /#/orders、/#/orders/{id}、/#/rules、/#/architecture、/#/tests：状态机、规则证据、10/10 人工对照、测试矩阵
- /pages/m2.html：预售列表、定金成团、工艺单、能力预检、派单/接单/质检/发货/结算/争议、台账、审计
- /pages/ai.html：行业切换、知识库、检索、智能体工具轨迹、工作流失败重试、CRM、三语站点/SEO、FDE 手册、17 步自检
- /pages/ip.html：双角色、40.4s 播放器、6 场 beats、12 分镜、41 素材、审核留痕、授权草稿、6 SKU、16 步自检
- /pages/evidence.html：11 项验收、模块探测、一键全量自检、证据包导出、运行历史

交互抽测（CDP 真实点击/输入）：

- M1：角色切换后“质检通过”按钮由 disabled 变可用，点击后状态 qc -> shipped，审计 +1。
- M2：误派 ws-jewel-02 时页面回填 5 项能力检查（工艺匹配红），正确工坊可接单；质检 fail 必须填备注。
- B：新建会话、提问（回复含 8%–10% 与 kb-wd-demo-outdoor#c1 等引用、工具轨迹 search_knowledge）、检索、询盘写 CRM、工作流运行/失败重试。
- C：播放/暂停/重播、12 格缩略图跳转、审核 pass/reject、授权草稿生成、SKU 表。
- 驾驶舱：一键自检 -> 11/11 -> 导出证据包，全部按钮可用；0 未捕获异常。

## 6. 代表性负向结果（证明校验真实生效）

- M1：壁厚 0.5 mm 铸件 422 CAST-WALL；使用范围 personal 纹样 422；internal 用途 422；设计师执行 accept 403；draft 直接 start_production 409；返工不填备注 422。
- M2：未达起订量不成团；误派能力不匹配 422（5 项检查中仅“工艺匹配”失败）；质检 fail 不填备注 422；连续 3 次返工升级 escalated；成功订单二次结算 409；非授权角色 403。
- B：workshop 创建工作流/询盘 403；非法邮箱 422；缺必填字段的流程运行失败且可重试；成功 run 重试 409；非法语言 404/422。
- C：工坊角色审核 403；删除 shot-01.wav 后播放器 manifest 422 asset_missing。
- 静态服务白名单：server.py、core.py、m1.db、tests 源码返回 404；仅页面/样式/脚本/文档/截图/证据包可访问。

## 7. 截图与视觉核验

- .scratch/m2-page.png：M2 页面 KPI、预售详情、定金表、工艺单入口
- .scratch/ip-page4.png：C 页面全页（1680x5600），播放器、分镜、素材、审核、授权、SKU
- .scratch/ai-page.png 与 .scratch/ai-clip-*.png：B 页面 KPI、知识库、智能体、工作流、CRM、三语站点、FDE
- .scratch/evidence-final.png：驾驶舱 11/11、48/48、49 步、证据包
- .scratch/index-nav.png：M1 首页新增四个扩展模块导航无破版

## 8. 本轮不证明什么

- 未做并发/压力测试；SQLite + ThreadingHTTPServer 是参考实现，生产需换数据库与部署方案。
- 场景与单测证明业务规则、状态机、分账与接口契约，不证明真实生产 SLA。
- 浏览器验证覆盖 Edge/Chromium；Safari/Firefox 未逐项验证。
- B 的“智能体”是本地确定性规则引擎（关键词 + n-gram + 意图路由），不是大语言模型；SEO 为确定性自检，不承诺搜索排名。
- C 无 MP4（环境无 ffmpeg），样片为浏览器内音频 + SVG 分镜 + SRT 字幕的可播放组合；TTS 依赖本机 Huihui 中文语音。
- 所有客户、工厂、预算、案例、角色、合同、SKU 均为合成/自制；不构成真实报价、版权或法律意见。

报告由实际命令输出与浏览器运行结果生成，未使用 PPT 或截图代替运行结果。

# CraftMesh · 工艺协同中台（ClawHunt #1724 可运行交付）

一个仓库、一条启动命令、一套数据层，覆盖任务书 A/B/C 三块与 M1–M4 的可运行纵切：工艺 AI 共创与 C2M 柔性定制（M1+M2）、六产业共享企业 AI 服务层（B）、文化 IP 短剧管线（C），外加一页可复跑的验收驾驶舱。

**所有数据、角色、工坊、客户、订单与台词均为合成/脱敏样例；所有素材为仓库内自制；所有"智能"判断由本地确定性规则完成，不调用外部大模型或外部 API。** 页面里的每个状态、金额、判定、审核结论都由本机 API 与 SQLite/JSON 实时生成，不是静态原型。

当前实测状态：**85/85 自动化测试通过**、M2/B/C 三套端到端场景通过、平台验收映射 **11/11 项（48/48 检查）**、证据包已导出。复跑与证据见 [TEST-REPORT.md](TEST-REPORT.md) 和 `/pages/evidence.html`。

## 快速开始

环境要求：Python 3.10+（只用标准库，无第三方依赖；本机实测 Python 3.12.14）、现代浏览器。SQLite 与 JSON 数据文件由服务端自动创建。

    python server.py

默认监听 http://127.0.0.1:8787/。指定端口用 `python server.py --port 8788`。

浏览器打开后可从左侧导航进入五个页面：

| 页面 | 路径 | 覆盖 |
| --- | --- | --- |
| M1 工作台 | / | 纹样授权、可制造性判定、报价、订单状态机 |
| M2 预售与工厂派单 | /pages/m2.html | C2M 预售成团 → 工艺单 → 派单 → 质检返工 → 分账 → 争议退款 |
| B 企业 AI 服务层 | /pages/ai.html | 双行业配置、知识库检索、规则智能体、自动化工作流、三语独立站/SEO、询盘 CRM、FDE 手册 |
| C 文化 IP 短剧管线 | /pages/ip.html | 双原创角色、剧本分镜、自制画面、本机配音与字幕、40.4 秒可播放样片、内容审核、授权与衍生品 |
| 验收驾驶舱 | /pages/evidence.html | 平台 11 条验收标准逐条证据、一键全量自检、证据包导出 |

五个页面均做了窄屏适配：390px 视口下侧栏折叠为顶部图标导航，宽表格在卡片内横向滚动，实测无横向溢出（验证记录见 [TEST-REPORT.md](TEST-REPORT.md)）。

## 在线演示（稳定入口 + 自动更新当前隧道地址）

- **稳定入口（域名不变）：https://gupeat.github.io/craftmesh-m1/**
- 当前在线 Demo：https://8f9787495987ce.lhr.life/
- 验收驾驶舱：https://8f9787495987ce.lhr.life/pages/evidence.html
- 完整源码包：https://8f9787495987ce.lhr.life/downloads/craftmesh-1724-source.zip
- 稳定入口是 GitHub Pages 上的静态页：它读取同目录 `docs/live.json`，把按钮指向当前隧道。localhost.run 免费隧道的主机名可能变化，`scripts/keep_public_tunnel.ps1` 在重连拿到新地址时调用 `scripts/publish_demo_url.py` 自动更新并推送 `live.json`，因此入口本身不会失效。
- 在线 Demo 依赖托管主机保持在线，不承诺与托管主机无关的 SLA；所有数据仍为合成/脱敏。若暂时打不开，源码包解压后一条命令即可在本机复现。

本机也可完全离线启动：

Docker 方式（可选）：

    docker build -t craftmesh .
    docker run --rm -p 8787:8787 craftmesh

## 主流程，可点通

1. **M1 工作台**：选纹样/工艺/材料与 12 个工艺参数 → 运行可制造性检查 → 查看 10 条规则逐条证据、授权快照与报价 → 创建订单草稿 → 在订单中心按角色推进状态（退回/质检退回必须写备注；越权与非法迁移被服务端拒绝）。
2. **M2 预售与制造协同**：创建预售（纹样授权校验 + 服务端报价/定金计算）→ 开放预售 → 支持者付定金 → 达到起订量自动成团并生成正式工艺单 → 派单前做 5 项能力预检（工艺/材料/尺寸/起订量/在制产能），不匹配 422 并逐项说明原因 → 工坊接单、开工、质检（不合格必须写原因并返工，超限升级）→ 发货 → 结算分账（平台 25% / 授权方 10% / 工坊余额）→ 争议按比例退款并写台账。
3. **B 企业 AI 服务层**：切换珠宝/木作两个行业（术语、知识库、工作流、站点文案随配置切换）→ 知识库检索返回切块与引用 → 规则智能体多轮对话并展示工具轨迹 → 自动化工作流按触发/条件/动作运行，含失败重试与运行记录 → 中英日三语独立站与 SEO 自检 → 询盘写入 CRM（阶段、负责人、金额）→ FDE 驻企交付手册。
4. **C 文化 IP 短剧管线**：远视/远听双原创角色手册 → 6 场剧本 → 12 格分镜（逐格时长、景别、台词）→ 自制 SVG 场景卡 → 本机 SAPI 中文配音 WAV + SRT 字幕 → 浏览器内时间轴播放器播放 40.4 秒样片 → 9 条审核规则跑合规/违规两条用例并留痕 → 12 条授权草稿与 6 个衍生品 SKU。
5. **验收驾驶舱**：点“一键全量自检”，逐条跑静态检查、模块探活与三套端到端场景，得到每条验收项的证据（文件、哈希、规则行、测试输出、场景步骤），可导出 Markdown 证据包。

## 一键验收

服务启动后，另开终端执行：

    python verify_all.py

它会依次检查服务探活、跑完全部单元测试、执行验收静态检查、依次跑 M2/B/C 三套端到端场景，并打印 PASS/FAIL 表（有失败时退出码非 0）。加 `--json` 输出机器可读结果，`--base` 指向其他地址。

只跑测试：

    python -m unittest discover -s tests -v

浏览器验收：打开 http://127.0.0.1:8787/pages/evidence.html ，点右上角“一键全量自检”；或直接访问 `/pages/evidence.html?autorun=1&export=1` 自动运行并导出证据包（写入 `data/evidence/packs/`，页面提供下载链接）。

## 三套端到端场景（服务端真跑，不是页面假动画）

| 模块 | 调用 | 步骤 | 说明 |
| --- | --- | --- | --- |
| M2 | `POST /api/m2/scenario` | 16 步 | 15 步成功 + 1 步故意误派给不具备工艺能力的工坊，返回 422 并回传 5 项检查明细 |
| B | `POST /api/ai/scenario` | 17 步 | 行业切换、知识库、检索引用、智能体多轮、工作流失败重试、三语站点、SEO、询盘转 CRM、FDE；含预期失败步骤（权限/缺失输入），按 `expectError` 判定 |
| C | `POST /api/ip/scenario` | 16 步 | 角色/剧本/分镜/时长/素材/播放器/配音/字幕/审核通过/审核拒绝/审核留痕/授权/衍生品；含 2 个预期失败（越权 403、缺失 WAV 被拦截） |
| 验收 | `POST /api/evidence/static-run` | 数十条检查 | 文件、哈希、规则样例、单元测试、模块探活与场景结果汇总为 11 条平台验收项 |

M1 另有 10 条人工规则基线：`core.human_rule_results()` 返回 10/10 与引擎一致，其中 3 条硬约束阻断。

## M1：规则、授权与订单状态机

- 10 条可制造性规则，其中 3 条硬约束：CAST-WALL（铸件最小壁厚）、INLAY-GAP（镶嵌最小间隙）、CARVE-GRAIN（逆纹雕刻限制）。硬约束失败阻断创建订单，软约束失败进入“需复核”。
- 授权校验显式逐项进行：来源、授权编号、使用范围、本次用途、二创许可；快照随单固化，用途与授权范围不符时判定与下单都会失败。
- 订单状态机 draft → submitted → accepted → rework → in_production → qc → shipped → settled → cancelled，越权 403、非法迁移 409、缺备注 422。

## M2：规则与数据文件可维护

`config/m2_rules.json`（平台抽成 2500bps、授权分成 1000bps、定金 30%、各工艺起订量、派单并发上限、返工上限、争议默认退款比例）与 `config/workshops.json`（4 个合成工坊的工艺/材料/尺寸/产能/交期）都是纯 JSON，非程序员可直接改；服务端按文件 mtime 热加载，改完刷新页面即生效。合成工坊均标注“合成样例，不代表真实工厂”。

## B：双行业与企业 AI 服务层

- 行业配置在 `config/ai_industries.json`，珠宝定制与木作定制各带术语表、知识库文档、站点三语文案、工作流模板与 CRM 阶段；切换行业后 API 与页面同步切换。
- 知识库：文档切块（可配置 chunk 大小/重叠），检索返回命中块、相似度与引用位置；支持草稿/发布状态。
- 智能体：本地确定性规则引擎（关键词/意图/槽位/工具调用），多轮上下文 + 工具轨迹 + 兜底话术；页面明确标注“本地规则引擎，非外部大模型”。
- 工作流：触发（询盘/表单）→ 条件 → 动作（写 CRM、发通知、生成摘要），运行记录含状态、耗时、失败原因与一键重试。
- 出海增长：中/英/日三语独立站、hreflang、SEO 自检（标题/描述/关键词覆盖/FAQ 等 8 项打分）、询盘表单落 CRM、FDE 驻企手册 Markdown。
- 配置在 `config/ai_engine.json`、`config/ai_handbook.json`、`config/ai_industries.json`，同样可改文件不写代码。

## C：文化 IP 短剧管线（全部素材自制）

- 双原创角色“远视/远听”：外观母题、声音画像、能与不能、禁用表达，来自 `config/ip_story.json`。
- 6 场剧本 → 12 格分镜，逐格含景别、时长、台词、音效；服务端强制校验总时长在 30–45 秒内（当前 40.4 秒）。
- 画面：12 张自制 SVG 场景卡 + 2 张角色卡，无真人照片、无外部素材。
- 声音与字幕：本机 Windows SAPI 中文语音逐格合成 12 段 WAV（22.05kHz 单声道），合并为 40.4 秒总配音；同步生成 12 段分镜 SRT 与总字幕。
- 播放器：浏览器 `<audio>` + 服务端媒体清单驱动时间轴，自动切场景、叠字幕、可拖动/跳转/重播/静音。
- 内容审核：9 条规则（真人肖像、历史人物、传统技艺表述、绝对化用语、医疗功效等），合规文案通过、违规文案被拒并命中规则，两次审核均留痕可查。
- 授权与衍生：12 条授权草稿条款（含免责声明，非法律意见）与 6 个衍生品 SKU 规格/分成。

## 数据、合规与边界

- 全部业务数据为合成或脱敏样例：合成纹样、合成工坊、合成订单、合成询盘、虚构山谷与角色；不含真实客户名单、真实工厂设备清单、真实版权归属或检测报告。
- 页面与文档不声称获得真实品牌/非遗/明星授权；不提供政策申报、财政测算、真实诊疗、线下施工、资质许可等业务。
- 本地支付/结算/退款只是台账演示，不对接真实支付通道；SEO 分数是确定性字符串检查，不承诺真实搜索排名；授权模板不构成法律意见。
- 角色权限在服务端强制（403），前端角色切换只影响可见动作；所有关键动作写审计事件。

## HTTP API 摘要

| 模块 | 端点 |
| --- | --- |
| M1 | GET /api/health、/api/bootstrap、/api/orders、/api/orders/{id}；POST /api/check、/api/orders、/api/orders/{id}/transition、/api/demo/reset |
| M2 | GET /api/m2/config、/api/m2/dashboard、/api/m2/campaigns、/api/m2/campaigns/{id}、/api/m2/production-orders、/api/m2/production-orders/{id}、/api/m2/dispatches、/api/m2/ledger、/api/m2/disputes、/api/m2/events；POST /api/m2/campaigns、/api/m2/campaigns/{id}/open｜pledge｜cancel、/api/m2/production-orders/{id}/dispatch｜capability｜start｜submit-qc｜qc｜ship｜settle、/api/m2/dispatches/{id}/respond、/api/m2/disputes、/api/m2/disputes/{id}/resolve、/api/m2/scenario、/api/m2/demo/reset |
| B | GET /api/ai/config、/api/ai/dashboard、/api/ai/knowledge、/api/ai/knowledge/{id}、/api/ai/search、/api/ai/sessions、/api/ai/sessions/{id}、/api/ai/workflows、/api/ai/workflows/{id}、/api/ai/workflows/runs、/api/ai/leads、/api/ai/inquiries、/api/ai/site/{lang}、/api/ai/seo、/api/ai/fde-handbook、/api/ai/events；POST /api/ai/knowledge、/api/ai/sessions、/api/ai/sessions/{id}/message、/api/ai/workflows/runs、/api/ai/workflows/runs/{id}/retry、/api/ai/inquiries、/api/ai/leads/{id}、/api/ai/scenario、/api/ai/demo/reset |
| C | GET /api/ip/config、/api/ip/dashboard、/api/ip/media-manifest、/api/ip/review-rules、/api/ip/reviews、/api/ip/license、/api/ip/skus、/api/ip/events；POST /api/ip/reviews、/api/ip/license、/api/ip/scenario、/api/ip/demo/reset |
| 验收 | GET /api/evidence/config、/api/evidence/dashboard、/api/evidence/runs、/api/evidence/runs/{id}、/api/evidence/packs；POST /api/evidence/static-run、/api/evidence/record、/api/evidence/export、/api/evidence/demo/reset |

所有 POST 可带 `role`（designer/ops/workshop/finance/buyer/admin，B/C 各有角色集），越权返回 403；错误统一为 `{"ok": false, "error": "...", "message": "..."}`。

## 目录结构

    server.py            HTTP 服务、静态白名单、扩展模块挂载
    core.py / store.py   M1 规则、授权、报价、状态机与 SQLite
    mod_m2.py            M2 预售/派单/质检/分账/争议（JsonStore + SQLite）
    mod_ai.py            B 知识库/智能体/工作流/站点/CRM/FDE
    mod_ip.py            C 剧本/分镜/媒体清单/审核/授权/衍生品
    mod_evidence.py      验收驾驶舱静态检查与证据包
    extensions.py        扩展模块容错加载与路由分发
    verify_all.py        一条命令验收 CLI
    config/              m2_rules.json、workshops.json、ai_*.json、ip_story.json、acceptance.json
    pages/               m2.html、ai.html、ip.html、evidence.html 及各自 js/css（共用 ui.js/shell.js/pages.css）
    media/               C 模块自制 SVG 场景、WAV 配音、SRT 字幕
    tests/               unittest 核心、API、M2、B、C 与验收配置测试
    data/                SQLite/JSON 数据与 evidence/packs 证据包
    docs/                B/C 验证记录
    index.html / app.js / styles.css   M1 页面
    Dockerfile / render.yaml          部署
    scripts/keep_public_tunnel.ps1    公网隧道断线自动重连守护

## 验证记录

- `TEST-REPORT.md`：全量测试、三套场景与浏览器截图记录。
- `docs/B-verification.md`、`docs/C-verification.md`：B/C 模块的逐项命令、输入、期望输出与实测结果。
- `data/evidence/packs/`：验收驾驶舱导出的 Markdown 证据包（含文件哈希、测试输出、场景步骤与结论）。

## 部署与公网演示

- 完整源码包（无需 Git 账号）：服务启动后访问 `/downloads/craftmesh-1724-source.zip`，同目录 `.sha256` 提供校验值；包内 `SOURCE-MANIFEST.json` 列出每个文件的字节数与 SHA-256。重新打包：`python make_source_bundle.py`。
- Docker：见上；`render.yaml` 提供 Render Blueprint（免费计划，`python server.py --host 0.0.0.0 --port $PORT`，健康检查 `/api/health`）。
- 稳定公网入口：GitHub Pages 静态页 https://gupeat.github.io/craftmesh-m1/ 读取 docs/live.json 获取当前隧道地址；localhost.run 免费隧道地址变化时由 `scripts/keep_public_tunnel.ps1` 调用 `scripts/publish_demo_url.py` 自动更新 live.json 并提交到 GitHub。私有 key 只保存在托管主机，不进入仓库。
- 备选：`cloudflared tunnel --url http://127.0.0.1:8787` 生成临时 trycloudflare 地址（重启会变化，只作应急）。
- 无外网依赖：全部素材与规则在仓库内，离线可跑。

## 排障

- 端口占用：`python server.py --port 8788`。
- 数据乱了：管理员角色下 POST `/api/demo/reset`（M1）或各模块 `/api/{m2,ai,ip}/demo/reset`；驾驶舱“重置演示数据”会清空运行记录与证据包索引。
- 场景会重置对应模块数据（M2/B/C 的 scenario 接口先 reset 再跑），演示前请留意。

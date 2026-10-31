# B 模块验证记录 · 企业 AI 服务层（双行业）

- 验证对象：ClawHunt #1724 可运行交付 · 模块 B（六产业共享企业 AI 服务层）
- 代码版本：mod_ai.py + pages/ai.html + pages/ai.js + pages/ai.css + config/ai_industries.json + config/ai_handbook.json
- 验证时间：2026-10-31 02:48（Asia/Shanghai）
- 运行环境：Python 3.12.14（仅标准库）、SQLite（本地文件）、无外部大模型/无外网 API
- 结论：18/18 模块单测通过，全量 85/85 单测通过；17 步全链路场景通过（15 步成功 + 2 步预期拒绝）；三语站点 SEO 三语均 100%、8 项检查全绿；页面在 Edge headless 下渲染与交互实测通过（截图见 3.5）。

## 1. 交付物与职责

| 文件 | 作用 |
| --- | --- |
| mod_ai.py | 双行业配置、知识库切块与检索、本地规则智能体（工具轨迹/引用）、自动化工作流（模板/运行/失败重试）、三语独立站与 SEO 检查、询盘写 CRM、FDE 驻企交付手册、审计事件 |
| config/ai_industries.json | 珠宝（jewelry）/ 木作（woodcraft）两套行业配置：知识种子、站点文案、FAQ、SEO 关键词、工作流模板、术语表、商品词表（productTerms，供线索解析）；非程序员可直接改配置 |
| config/ai_handbook.json | FDE 驻企交付手册（9 节、3900 字符） |
| pages/ai.html + ai.js + ai.css | B 模块工作台：行业切换、知识库台账/详情/检索、智能体会话、工作流实例与运行、CRM 线索、三语站点预览与 SEO、FDE 手册、17 步自检 |
| tests/test_ai.py | 18 个单元测试（临时 SQLite，不污染 data/ai.db） |
| docs/B-verification.md | 本文件 |

数据合规：所有客户、工坊、价格、案例均为合成或脱敏样例；页面与接口均标注 sampleData/合成声明；智能体为本地确定性规则引擎（关键词 + 字符 n-gram 检索 + 意图路由），不调用外部大模型，不产生真实外发。

## 2. 可复跑命令

~~~bash
cd clawhunt/1724-demo

# 1) 模块单测（18 个）
python -m unittest tests.test_ai -v

# 2) 全量单测（85 个，含 M1/M2/验收驾驶舱/C）
python -m unittest discover -s tests -v

# 3) 启动服务后跑 17 步全链路场景
python server.py --host 127.0.0.1 --port 8787
curl -s -X POST http://127.0.0.1:8787/api/ai/scenario -H "Content-Type: application/json" -d "{\"role\":\"admin\"}"

# 4) 知识库/站点/手册接口探活
curl -s http://127.0.0.1:8787/api/ai/config
curl -s http://127.0.0.1:8787/api/ai/knowledge
curl -s http://127.0.0.1:8787/api/ai/site/en
curl -s http://127.0.0.1:8787/api/ai/fde-handbook

# 5) PATCH 推进线索（任务书契约；先 GET 一次让兼容层完成安装）
curl -s -X PATCH http://127.0.0.1:8787/api/ai/leads/<lead-id> \
  -H "Content-Type: application/json" \
  -d "{\"stage\":\"contacted\",\"note\":\"电话确认\",\"role\":\"admin\"}"
~~~

说明：上述命令默认操作 8787 主服务；本次验证为避免干扰 leader，使用 8899 隔离实例（独立 SQLite：.scratch/ai_http2.db），未触碰 8787。

## 3. 实测结果

### 3.1 单元测试（2026-10-31 02:48）

命令：python -m unittest tests.test_ai -v
结果：Ran 18 tests in 2.973s · OK（18 passed / 0 failed）

覆盖点与断言：
1. 配置：jewelry/woodcraft 双行业、2 个流程模板、agent.chat 权限仅 admin/ops/designer（workshop 不包含）、engine.disclosure 声明本地规则、sampleData=true。
2. 种子知识：woodcraft 4 篇已发布、12 个切块；每篇 chunkCount>=1；详情首个切块 index=1。
3. 检索：查询“户外木作含水率控制在多少”命中 >=1 条（<=topK 3）；scanned.chunks=12；每条命中含 docId#cN 引用、score>0、docTitle、text。
4. 行业切换：woodcraft -> jewelry 后知识库行业变化、站点标题变化且含“珠宝”；可切回。
5. 智能体知识意图：intent=search_knowledge、intentLabel=知识库检索；toolCalls[].tool=search_knowledge；citations 含 #c；回复包含 8% 或 10%；engine=本地规则引擎；会话历史 >=2 条。
6. 智能体留资意图：intent=create_lead、tool=create_lead；CRM 线索数 +1，邮箱与阶段 new 正确。
7. 工作流成功：模板 7 步全部 ok；生成 lead-/quote-；评级 A；实例状态 active、runCount=1。
8. 工作流失败重试：缺邮箱时第 1 步失败（failed）；补全输入重试成功、attempt=2、retryOf=原 run、新 run id。
9. 成功 run 不可重试：抛 AIError status=409。
10. 询盘校验：合法询盘 stage=new、source=inquiry-form；非法邮箱 422 且提示“邮箱”；缺字段 422。
11. 线索阶段推进：contacted 写入 history，非法阶段抛错。
12. 三语站点/SEO：zh/en/ja 三套标题互不相同；每语 8 项检查全 true；关键词覆盖率 100%；robots=noindex,nofollow；非法语言抛错。
13. FDE 手册：>=3000 字符、>=8 节、含“访谈”与 Markdown 结构。
14. 权限：workshop 创建工作流/询盘均 403；workshop 视角 workflow.write 不允许。
15. 重置：reset 后 documents>=4、chunks>=12；CRM 线索 0、工作流实例 0、会话 0；模板仍为 2。
16. 仪表盘：documents>=4、chunks>=12、模板 2、站点语言 3、engine.id=local-rules。
17. 17 步场景：ok=true、steps=17、expectedFailures=2、engine=本地规则引擎、siteLanguages=[zh,en,ja]。
18. 自然询盘解析：无“想做/咨询”动词、仅给“王女士 + 邮箱 + 预算 + 黑胡桃餐桌 + 来自日本”时，create_lead 工具仍能提取姓名/邮箱/产品/预算/国家（JP），并真实写入 CRM。

全量回归：python -m unittest discover -s tests -v -> Ran 85 tests in 8.061s · OK。

### 3.2 17 步全链路场景（HTTP，2026-10-31 02:46）

POST /api/ai/scenario（role=admin）返回 ok=true，steps=17，summary：

- steps=17、passed=15、expectedFailures=2
- industry=woodcraft、documentId=kb-wd-demo-outdoor、sessionId=sess-*
- agentLeadId=lead-*、inquiryLeadId=lead-*、workflowId=wf-*
- failedRunId=run-*、retriedRunId=run-*
- siteLanguages=[zh,en,ja]、engine=本地规则引擎

两步预期拒绝为演示“权限与空值校验真实生效”：越权角色写入被 403 拒绝、缺少必填字段的流程运行失败并可重试；其余 15 步为真实业务写入。

### 3.3 三语站点与 SEO（HTTP）

| 语言 | 关键词覆盖率 | 8 项检查 | robots |
| --- | --- | --- | --- |
| zh | 100.0% | 全部通过 | noindex,nofollow |
| en | 100.0% | 全部通过 | noindex,nofollow |
| ja | 100.0% | 全部通过 | noindex,nofollow |

说明：SEO 为确定性字符串匹配（title/description/关键词/内容区块/FAQ/关键词覆盖率/三语 hreflang），不承诺真实搜索排名；演示站 robots 明确 noindex,nofollow，避免被搜索引擎收录。

### 3.4 知识库与工作流实测

- woodcraft 种子知识：4 篇已发布文档、12 个切块（约 160 字/块）；检索结果引用形如 kb-wd-demo-outdoor#c1。
- 工作流模板 2 个：wf-wd-inquiry（7 步：校验必填 -> 检索含水率/交期 -> 线索分级 -> 写 CRM -> 生成报价草稿 -> 通知项目组 -> A 级升级提醒）、wf-wd-site-seo（3 步）。
- 失败重试：run 记录含 failedStep、attempt、retryOf；重试生成新 run，不覆盖失败记录。
- 运行历史写入 SQLite，页面可展开查看逐步状态、耗时与失败原因。

### 3.5 页面实测（Edge headless，1680 宽）

页面 /pages/ai.html 渲染与交互均从 /api/ai/* 实时取数，0 JS 异常：

- 顶部 6 张 KPI：知识文档、CRM 线索、工作流实例、运行次数/成功率、智能体会话、站点语言。
- 知识库台账 4 篇种子文档（自检后会多 1 篇演示文档）+ 详情切块 + 检索命中（带 docId#chunk 与分数）。
- 智能体：新建会话、提问、回复 2 条气泡、工具轨迹（search_knowledge 成功、参数、耗时）、引用片段。
- 工作流：模板 2 个、从模板创建实例、运行 7 步全绿、失败补全后重试 attempt=2。
- CRM：询盘表单写入 CRM、阶段推进（新询盘 -> 已联系）与历史记录。
- 出海：中文/English/日本語切换、SEO 100 分与 8 项检查、FDE 手册展开/收起。
- 一键全链路自检：17 步结果逐条展示（15 通过 + 2 预期拒绝）。
- 权限：切到 buyer（客户/销售）后角色条显示“可执行 4 / 11 项动作，7 项将被服务端拒绝”；自检按钮禁用、知识库提交禁用、表单 data-allowed=0；CDP 读取到 0 个可运行工作流按钮，服务端越权实测 403。

截图（Edge headless，1680 宽；目录 C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch/）：

| 截图 | 内容 | 尺寸/大小 |
| --- | --- | --- |
| ai-first-final.png | 最新首屏：引擎 chip、行业切换、17 步自检面板、6 张 KPI、知识库台账与首篇切块详情 | 1680×2400 / 493KB |
| ai-workflow-failed.png | 工作流缺邮箱失败：failedStep #1「缺少必填字段：email」与重试表单 | 1680 宽 |
| ai-workflow-retried.png | 补齐邮箱重试成功：attempt=2、retryOf 原失败 run、7 步全绿 | 1680 宽 |
| ai-crm-after.png | CRM 阶段由“新询盘”推进到“已联系”，备注与阶段历史落库 | 1680×1025 / 144KB |
| ai-growth-en.png | English 独立站预览 + SEO 100%、8 项检查、关键词覆盖 | 1680 宽 / 237KB |
| ai-handbook.png | FDE 手册 9 节展开，表格/列表/标题渲染 | 1680×2786 / 431KB |
| ai-verified-full.png | 交互后的整页长截图 | 1680 宽 / 1.6MB |

页面实测方式：Edge legacy headless 开启 remote debugging（9225），Node WebSocket 走 CDP 点击/填表/读取 DOM；首屏 BOOT_ERRORS 0、LOG_ERRORS 0。静态截图命令：

~~~bash
"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --disable-gpu \
  --hide-scrollbars --no-first-run --user-data-dir=<profile> --window-size=1680,2400 \
  --virtual-time-budget=9000 --screenshot=<png> http://127.0.0.1:8899/pages/ai.html
~~~

### 3.6 HTTP 端点实测（8899 隔离实例，2026-10-31 02:45）

用 Node/run_code 的 fetch 逐端点实跑，关键结果：

| 端点 | 实测 |
| --- | --- |
| GET /api/ai/config?industry=woodcraft | 200；2 个行业、11 项权限、engine=本地规则引擎；文档 5 / 切块 14（含自检文档） |
| POST /api/ai/industry | 200；industry=woodcraft |
| POST /api/ai/knowledge | 200；新建 kb-408f0f05，published，自动切块 1 |
| GET /api/ai/knowledge/{id} | 200；chunk c1；列表 6 篇 / 15 块 |
| POST /api/ai/search（命中） | 200；3 条，首条 kb-wd-demo-outdoor#c2 score=27，tookMs=8.64 |
| POST /api/ai/search（空查询） | 400；empty_query“检索词不能为空，请输入术语或问题关键词” |
| POST /api/ai/search（无命中） | 200；count=0，附 3 条改词/文档状态建议，不编造 |
| POST /api/ai/sessions + messages | 200；4 条消息；首轮 search_knowledge 引用 #c；二轮 create_lead 真实写 CRM |
| POST /api/ai/inquiries | 200；lead-418a5cf7，stage=new |
| PATCH /api/ai/leads/{id} | 200；stage=contacted，notes/history 写入（兼容层，见 4 节第 7 条） |
| POST /api/ai/workflows | 200；wf-aefb8294，7 步 |
| POST /api/ai/workflows/{id}/run（成功） | 200；status=success，7 步，lead-/quote-，评级 A，53.22ms |
| POST /api/ai/workflows/{id}/run（缺 email） | 200；status=failed，failedStep #1 missing_input“缺少必填字段：email” |
| POST /api/ai/workflows/runs/{id}/retry | 200；status=success，attempt=2，retryOf=原 run，7 步 |
| GET /api/ai/workflows/runs | 9 条；success 6 / failed 3 |
| GET /api/ai/site/{zh,en,ja} | 200；三套标题分别为山门木作 / Shanmen Woodworks / 山門木工 |
| GET /api/ai/seo?lang=en | score=100，coverage=100%，8/8 检查，alternates 三语均带 lang |
| GET /api/ai/fde-handbook | 200；3900 字符、9 节 |
| POST /api/ai/knowledge（role=buyer） | 403；forbidden“角色 buyer 不能执行「写入知识库」” |
| POST /api/ai/scenario | 200；17 步、passed=15、expectedFailures=2，其余 summary 字段齐全 |

## 4. 已知限制与边界

1. 智能体为本地规则引擎（关键词 + 字符 n-gram + 意图路由），不是大语言模型；回复与引用来自本地知识库，不生成未经检索的内容。
2. 知识库切块为固定长度（约 160 字），未做向量嵌入与语义检索；检索为确定性打分。
3. 工作流为顺序步骤执行，不含并行分支、定时触发与外部系统回调；通知为站内模拟。
4. 站点为三语演示数据，不接入真实 CMS；SEO 检查为规则化自检，不代表搜索引擎实际收录/排名。
5. 所有客户、邮箱、预算、案例均为合成/脱敏样例（example.com），不做真实外发；不包含真实客户数据、真实工厂产能或真实报价承诺。
6. 仅在本机 Python 3.12 与 Edge/Chromium 验证；未验证 Safari/Firefox 的边界样式。
7. PATCH 兼容层：server.py 只实现 do_GET/do_POST，而任务书要求 PATCH /api/ai/leads/{id}。mod_ai 在导入后 0.4 秒定时、并在首次 GET/POST 时，给运行时 ApiHandler 动态补 do_PATCH，仅把 /api/ai/* 请求转发到既有 POST 路由；未修改 server.py / extensions.py。POST 仍可用。若进程启动后 0.4 秒内的第一个请求就是 PATCH，可能仍返回 501；页面与验收流程先 GET config，不会触发该边界。
8. 智能体线索提取使用 config/ai_industries.json 的 productTerms 词表（珠宝/木作各一组）与邮箱/预算/国家正则，属于确定性规则，不保证覆盖所有自然语言表达；未识别时会明确要求补邮箱/需求，不静默编造。

## 5. 验收映射（对应任务书 0)-10) 与平台验收）

- 0) 可运行成果：python server.py 一条命令启动；页面与接口同源。
- 1) 四主流程：B 的“知识库 -> 智能体 -> 工作流 -> CRM”在同一服务内可点通。
- 5) 知识库 + 智能体 + 自动化工作流：见 3.1/3.4。
- 6) 多语言独立站/SEO/CRM：见 3.3/3.5；FDE 手册 9 节。
- 9) 文档与实现一致：README 列出 /pages/ai.html 与 API；本文件附可复跑命令与实测结果。
- 10) 合规：合成/脱敏声明、noindex、本地规则引擎声明、无真实外发。

## 6. 给 leader 的验收摘要

- 交付物：mod_ai.py（后端全部业务与 HTTP 路由）、pages/ai.html + ai.js + ai.css（可点通工作台）、config/ai_industries.json（双行业全量配置）、config/ai_handbook.json（FDE 手册）、tests/test_ai.py（18 用例）、docs/B-verification.md（本文件）。
- 页面：http://127.0.0.1:8787/pages/ai.html （本次验证用 8899 隔离实例）。
- 端点：GET config / dashboard / knowledge / knowledge/{id} / sessions/{id} / workflows / workflows/runs / workflows/{id} / leads / site/{lang} / seo / fde-handbook / events；POST industry / knowledge / search / sessions / sessions/{id}/messages / workflows / workflows/{id}/run / workflows/runs/{runId}/retry / inquiries / leads/{id} / scenario / demo/reset；另有 PATCH /api/ai/leads/{id}（兼容层）用于推进线索。
- 场景：POST /api/ai/scenario 返回 17 步，15 成功 + 2 预期拒绝（buyer 写知识库 403、空检索 400）；覆盖切行业→建文档→检索→智能体两轮（检索/建线索）→询盘→CRM 推进→工作流成功→缺字段失败→重试成功→三语站点→SEO→FDE→越权。
- 测试：tests/test_ai.py 18/18 通过；全量 discover 85/85 通过。
- 证据截图：.scratch/ai-first-final.png、ai-workflow-failed.png、ai-workflow-retried.png、ai-crm-after.png、ai-growth-en.png、ai-handbook.png、ai-verified-full.png。
- 已知问题：PATCH 依赖 mod_ai 的运行时兼容层（未改 server.py）；智能体是本地规则引擎；知识库为关键词/n-gram 检索而非向量；工作流为顺序执行；站点为三语演示配置，robots noindex；所有客户/工坊/价格均为合成样例。

# CraftMesh M1 测试与验证记录

最近一次实测：2026-10-30 13:22（Asia/Shanghai，UTC+8）
环境：Windows / CPython 3.12.14 / 仅标准库 / SQLite 本地文件
范围：M1 参考实现，全部为合成演示数据

## 1. 自动化测试

命令：

    cd 1724-demo
    python -m unittest discover -s tests -v

结果：

    Ran 30 tests in 0.987s
    OK

组成：21 个核心单测 + 9 个真实 HTTP API 集成测试。API 测试会启动 ThreadingHTTPServer，通过 JSON 请求走真实路由，不 mock 传输层；测试数据库为临时 SQLite 文件，结束后关闭并清理。

## 2. 覆盖内容

| 测试组 | 覆盖 | 结果 |
| --- | --- | --- |
| 规则引擎 | 10 条规则、3 条硬约束；薄壁、镶嵌间隙、逆纹雕刻阻断；软约束返回需复核 | PASS |
| 授权校验 | 原创通过；非商业范围拒绝；内部用途拒绝；二创未授权拒绝；授权纹样缺来源编号拒绝 | PASS |
| 人工规则对照 | 10 条人工判定与引擎结论 10/10 一致；3 条硬约束阻断 | PASS |
| 订单快照 | 授权字段、用途与报价随单固化；硬约束失败的订单创建被拒绝 | PASS |
| 状态机 | 全链路迁移；非法前置状态拒绝；越权角色拒绝；退回必须备注 | PASS |
| HTTP API | health / bootstrap / check / 创建订单 / 订单详情 / 状态迁移 | PASS |
| 权限与重置 | 非管理员重置返回 403；管理员重置成功 | PASS |
| 静态白名单 | 首页与 app.js 可访问；server.py、core.py、m1.db、tests 源码返回 404 | PASS |
| 持久化 | 订单与审计写入 SQLite，临时库关闭与清理 | PASS |

代表性负向结果：

- POST /api/orders 使用壁厚 0.5 mm 的铸件：422，硬约束 CAST-WALL 阻断。
- POST /api/orders 使用使用范围为 personal 的纹样：422，授权校验拒绝。
- POST /api/orders 使用 internal 用途：422；POST /api/check 返回 license.ok=false，快照记录 use=internal。
- 设计师执行 accept：403；从 draft 直接 start_production：409。
- request_rework / reject_qc 不填备注：422。
- 非管理员 POST /api/demo/reset：403。
- GET /server.py、/core.py、/m1.db、/tests/test_core.py：404，静态服务只允许页面、样式、脚本、文档和截图。

## 3. 浏览器验证

用 Edge headless 渲染并检查以下页面：

- http://127.0.0.1:8787/ ：工作台、KPI、判定摘要、授权快照、报价、订单列表
- http://127.0.0.1:8787/#/orders ：订单状态机与角色权限
- http://127.0.0.1:8787/#/orders/ORD-AC97896D ：订单详情、规则证据、角色化动作、审计
- http://127.0.0.1:8787/#/rules ：10 条规则、3 条硬约束、10/10 人工对照、授权台账
- http://127.0.0.1:8787/#/architecture ：请求链路、责任边界、A01–A10 对照
- http://127.0.0.1:8787/#/tests ：测试矩阵与本报告入口

页面显示 API 在线；订单数据由服务端 SQLite 生成，刷新不丢失；6 个入口均可通过 hash 直达。

交互验证（Edge CDP，同一页面）：

- 默认“设计/工艺”角色打开“质检中”订单：质检通过按钮为 disabled，页面给出切换角色的提示。
- 切换到“质检/质检组”后按钮启用，提示消失；点击“质检通过”后状态从 qc 变为 shipped，审计从 5 条增至 6 条，toast 显示“状态已迁移：已发货”。
- 全程没有 Runtime 异常或 console error；验证完成后通过管理员重置并重新生成 3 张演示订单，未影响交付数据。

## 4. 种子数据

命令：

    python seed_demo.py --base http://127.0.0.1:8787

生成 3 张合成订单：待评审、质检中、已结算；当前统计为订单 3、在途 2、审计 14 条。种子脚本只调用公开 HTTP API，不直接写库。

## 5. 本轮不证明什么

- 未做并发/压力测试；SQLite 与 ThreadingHTTPServer 是参考实现，生产需换数据库与部署方案。
- 浏览器验证是 headless 渲染与 DOM 检查，不是完整的 Playwright/Cypress E2E 套件。
- 未接真实工厂排产、支付、退款/争议、多语言站点、文化 IP 短视频管线；这些属于 M2–M4。
- 规则是合成规则，正式制造仍需工艺师复核；授权数据是合成样本，不构成真实版权意见。

报告由实际命令输出生成，未使用 PPT 或截图代替运行结果。

# 模块 C · 文化 IP 短剧管线 —— 验证记录

- 模块：C / A07 内容资产系列
- 页面：`/pages/ip.html`（独立自测实例 `http://127.0.0.1:8791/pages/ip.html`；leader 的 8787 未触碰）
- 验证日期：2026-10-31（Asia/Shanghai）
- 结论：**可运行纵切已完成。后端 14 个单元测试通过；全链路 scenario 16/16 步通过（2 步为设计内预期失败）；41 项媒体资产真实存在；页面在 Edge headless 中加载、播放、跳转、审核、草稿生成均实测通过。**
- 性质声明：本模块全部角色、剧本、画面、声音、审核规则、合同模板与衍生品规格均为**合成/原创演示样例**，不含真人形象，不引用真实客户、真实工厂、真实非遗项目或第三方版权素材。所有“智能”判断均为**本地确定性规则引擎，非外部大模型**。

---

## 1. 一页结论

| 项目 | 结果 |
| --- | --- |
| 原创角色 | 2 个：远视（视觉） / 远听（听觉），含母题、性格、声音画像、能与不能 |
| 剧本 / 分镜 | 6 个节拍，12 格分镜；总时长 **40,400 ms（40.4 秒）**，在 30–45 秒约束内 |
| 媒体资产 | **41 项存在 / 0 缺失**：12 场景 SVG + 12 配音 WAV + 12 分镜 SRT + 2 角色 SVG + 1 海报 + 1 主音轨 WAV + 1 主字幕 SRT |
| 主音轨 | `/media/voice/ip_sample.wav`，实测 **40,400 ms / 22,050 Hz / 单声道 / 16-bit**，1,781,684 bytes |
| 审核 | 9 条规则；合规样例 pass，违规样例 reject（命中 5 条），每次审核写入本地 SQLite 留痕 |
| 授权 / 衍生品 | 12 条合同草稿条款 + 明确“模板样例，不构成法律意见”；6 个合成 SKU，全部标“待授权” |
| 权限 | 服务端逐次校验；工坊角色审核返回 403，场景含预期失败步骤 |
| 自动化测试 | `tests/test_ip.py`：**14 tests / 0 failures / 0 errors**（0.519s） |
| 全链路自检 | `POST /api/ip/scenario`：**16 / 16 步通过，预期失败 2，意外 0** |
| 页面 | 首屏双角色卡、播放器、分镜表、审核台、合同草稿、SKU、16 步自检面板均渲染成功；重载后 JS 异常/错误级 console 日志为 0 |

---

## 2. 复跑方式与环境

### 2.1 启动独立实例（不要占用 leader 的 8787）

在本仓库根目录执行：

```bash
PYTHONIOENCODING=utf-8 \
C:/Users/xibei/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe \
server.py --host 127.0.0.1 --port 8791
```

打开：

```text
http://127.0.0.1:8791/pages/ip.html
```

说明：本验证使用独立端口 8791，验证结束后已终止自测服务；8787 始终未被重启或干扰。若 8791 被占用，可换成任意空闲端口，页面与 API 均走相对路径。

### 2.2 重新生成全部离线媒体

```bash
PYTHONIOENCODING=utf-8 \
C:/Users/xibei/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe \
scripts/gen_ip_assets.py
```

- 生成 12 个场景 SVG、2 个角色 SVG、海报、12 个分镜 SRT、主 SRT、12 个 WAV、主 WAV，并重算 `media/manifest.json`。
- 如只想重画 SVG/SRT、跳过 TTS，可加 `--no-voice`；该模式会保留已有 WAV 并重新计算清单。
- 需要 Windows 中文语音 **Microsoft Huihui Desktop**；脚本使用 PowerShell 5.1 `System.Speech`，采样格式 22,050 Hz / 16-bit / mono。
- **PowerShell 5.1 的 UTF-8 BOM 注意**：`scripts/make_voice.ps1` 由 Python 以 `'\ufeff'` 前缀写成 UTF-8 **带 BOM**（文件头 `EF BB BF`）。否则 5.1 用 `-File` 执行含中文的 .ps1 会报 ParserError。复跑时不要用会去掉 BOM 的编辑器重存。
- 生成脚本在写文件前会校验分镜总时长必须在 30,000–45,000 ms；不满足会拒绝生成。

### 2.3 单元测试

```bash
PYTHONIOENCODING=utf-8 \
C:/Users/xibei/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe \
-m unittest tests.test_ip -v
```

测试使用临时数据目录并 patch `mod_ip.DATA_DIR/DB_PATH/_store`，不会修改真实 `data/ip.db`；每个用例前 reset。输出见第 7 节。

### 2.4 复跑一份干净的演示数据

```bash
curl.exe -s -X POST http://127.0.0.1:8791/api/ip/scenario \
  -H "Content-Type: application/json" --data "{\"role\":\"admin\"}"
```

scenario 会先清空自己的审核/授权台账，再重跑全链路，因此可重复执行。

---

## 3. 数据文件与规则说明

### 3.1 `config/ip_story.json`

单文件保存了全部可维护内容，前后端均从这里读取，改 JSON 不需要改 Python：

| 区段 | 内容 |
| --- | --- |
| `module` / `sampleData` | 模块元信息、页面标题、合成样例声明、本地规则引擎说明 |
| `characters` | 2 个原创角色：名字/罗马字、身份、tagline、设定、外观母题、配色、性格、声音画像、能做什么、不能做什么、头像路径、符号 |
| `story` | logline、synopsis、6 个节拍（每拍覆盖哪些镜号）、剧本备注 |
| `shots` | 12 格分镜：镜号、场景、时长 ms、画面描述、镜头/构图、角色、说话人、字幕台词、音效、场景类型、SVG/WAV/SRT 路径、语速 |
| `media` | 主音轨/主字幕、语音名、画布尺寸、30–45 秒约束、逐镜语音留白、时长容差 |
| `review` | 文案长度约束、9 条审核规则（关键字/否定词/豁免词/缺失声明型）、合规与违规样例、结论标签 |
| `license` | 模板版本、12 条条款、用途/区域/期限选项、基础授权金（800,000 分 = 8,000 元）、衍生品分成 8%、免责声明 |
| `derivatives` | 6 个 SKU：尺寸/材质/工艺/包装、起订量、建议零售价、分成比例、状态“待授权” |
| `permissions` / `actors` | 5 个业务能力 × 角色白名单；角色中文名 |

### 3.2 双角色

| 角色 | 身份 | 外观母题 | 声音画像 | 能 / 不能（各 3 条） |
| --- | --- | --- | --- | --- |
| 远视 YUANSHI | 守灯人 / 视觉角色 | 单圆镜片、折光纸棱、深青披风、四十五度光束 | Microsoft Huihui Desktop / rate 0，低沉、句尾收得快 | 看见远处灯光与完整光路；用单圆镜片折光点火；记住山谷里亮过的每一扇窗 / 听不见石头里的回声；替别人做决定；改变已经发生的事 |
| 远听 YUANTING | 听潮人 / 听觉角色 | 贝壳耳廓、同心声波、朱砂披带、纸鹤折角 | Microsoft Huihui Desktop / rate 2，语速偏快、句尾上扬 | 分辨回声方向与距离；听见旧物里残留的声音；模仿一段只听一次的旋律 / 看见光路；读心或预知未来；让已经消失的声音永久留下 |

### 3.3 6 节拍 / 12 分镜 / 时长

| 节拍 | 覆盖镜号 | 时长合计（ms） |
| --- | --- | --- |
| B1 灯将熄 | 01–02 | 6,200 |
| B2 失声的纸鸟 | 03–04 | 6,600 |
| B3 折光点灯 | 05–06 | 7,000 |
| B4 回声归位 | 07–08 | 6,600 |
| B5 山谷亮灯 | 09–10 | 6,800 |
| B6 守夜人 | 11–12 | 7,200 |
| **合计** | **12 格** | **40,400（40.4s）** |

逐格时长（ms）：`3200, 3000, 3400, 3200, 3600, 3400, 3000, 3600, 3200, 3600, 3200, 4000`。代码用逐镜 `durationMs` 求和校验总时长，并把结果同时写入 `/api/ip/story`、`/api/ip/media-manifest` 与 dashboard；页面显示“通过 / 30.0 秒–45.0 秒”。

### 3.4 审核规则（9 条）

| rule | 中文标签 | 严重级 | 典型命中 | 处理建议 |
| --- | --- | --- | --- | --- |
| real_person | 真人形象与肖像 | blocker | 真人扮演、真人照片 | 改用自制 SVG 角色；如确需真人素材，附肖像授权与监护人同意 |
| medical_claim | 医疗与功效宣称 | blocker | 包治百病、治愈失眠 | 删除医疗/疗效承诺；剧情需要时加“虚构情节，不构成医疗建议” |
| violence | 暴力与惊吓 | blocker | 血腥、残肢、惊吓儿童 | 弱化画面与音效，增加分级提示 |
| minor | 未成年人与出镜 | major | 未成年人出镜、儿童演员 | 改为非真人角色；如确需，补监护人书面同意与平台青少年模式 |
| heritage_claim | 传统技艺真实性 | major | 非遗、传承人、古法 | 标注“虚构/合成样例”；若涉及真实技艺，补顾问与来源说明 |
| adaptation | 改编与版权授权 | major | 改编自、引用、网络热曲 | 说明改编来源、授权链与二创边界；未授权不得使用第三方素材 |
| copyright_statement | 原创 / 授权声明 | minor（缺失型） | 文案缺少原创/授权/版权/许可/自制 | 补充原创声明、授权范围与素材来源 |
| privacy_contact | 隐私与联系方式 | major | 手机号、微信号、住址 | 删除或脱敏个人信息，改用表单收集 |
| commercial_overclaim | 商业夸大与收益承诺 | blocker | 保证收益、稳赚、全网第一 | 删除保证性表述，给出可核验的口径与风险提示 |

规则支持否定词与豁免词（如“无真人扮演”“虚构”），审核结论：有 blocker → `reject`；仅有 major/minor → `revise`；无命中 → `pass`。审核结果保存 `reviewId / at / role / target / text / verdict / findings / counts`，可在页面历史与 `GET /api/ip/reviews` 查询。

### 3.5 授权与衍生品

- 合同模板版本 `IP-LIC-TPL-1.0`，12 条：合同主体、授权标的、授权用途、授权区域、授权期限、授权费用、署名与宣传、内容审核、衍生品规范、知识产权归属、违约与终止、争议解决与声明。
- 每个草稿带唯一 `draftNo`（如 `IP-LIC-20261031-0DB4D875`）与 `status: draft`，正文明确“模板样例，不构成法律意见 / 不产生真实授权效力”。
- 6 个 SKU 均为合成规格（亚克力立牌、线装笔记本、帆布袋、徽章盲袋、明信片套装、纸影小夜灯）；起订量/零售价/8% 分成仅用于演示，不代表真实供应商报价或产能，全部状态“待授权”。

---

## 4. 真实媒体证据

### 4.1 主音轨（Python `wave` 实测，不是声明值）

```text
master_real 40400 22050 1 2 890820
# 40400 ms / 22050 Hz / 1 channel / 2 bytes sample / 890,820 frames
bytes 1781684
```

`media/manifest.json` 记录的同样是 `durationMs: 40400, sampleRate: 22050, channels: 1, bytes: 1781684`。主音轨由 12 段真实 SAPI WAV 按分镜起点拼接并补零/裁剪到 40.4 秒；每段配音时长均不超过对应镜格。

### 4.2 12 段配音逐镜核对

| 镜号 | 场景 | 镜格 ms | WAV 实测 ms | 采样率 | 是否入槽 |
| --- | --- | ---: | ---: | ---: | --- |
| 01 | 回声邮局 · 外景 · 夜 | 3200 | 3155 | 22050 | 是 |
| 02 | 石阶 · 雾中 | 3000 | 2567 | 22050 | 是 |
| 03 | 邮局窗前 | 3400 | 3218 | 22050 | 是 |
| 04 | 石中旧声 | 3200 | 2970 | 22050 | 是 |
| 05 | 旧旋律 · 纸带 | 3600 | 3527 | 22050 | 是 |
| 06 | 折光 | 3400 | 3165 | 22050 | 是 |
| 07 | 灯芯复燃 | 3000 | 2840 | 22050 | 是 |
| 08 | 纸鸟振翅 | 3600 | 2705 | 22050 | 是 |
| 09 | 山谷亮灯 | 3200 | 3034 | 22050 | 是 |
| 10 | 屋顶 · 并肩 | 3600 | 2553 | 22050 | 是 |
| 11 | 远视的答案 | 3200 | 2334 | 22050 | 是 |
| 12 | 片尾 · 山谷回声 | 4000 | 3723 | 22050 | 是 |

配音总时长 35,791 ms（纯语音），主音轨 40,400 ms（含留白与镜格对齐），脚本与 API 都做“逐段音频 ≤ 镜格”检查。

### 4.3 SRT 示例

主字幕 `media/subtitles/ip_sample.srt` 共 12 条 cue，首条：

```srt
1
00:00:00,000 --> 00:00:03,080
山谷尽头的灯，今晚只剩一线。

2
00:00:03,200 --> 00:00:06,080
等等，我听见灯在抖。

3
00:00:06,200 --> 00:00:09,480
纸鸟把最后一句话，咽进了石头。
```

分镜字幕 `media/subtitles/shot-01.srt` 同时存在，时间轴相对该镜从 0 开始，供播放器按镜格叠加。

### 4.4 画面与播放器

- 12 个场景 SVG 全部为脚本生成的几何纸影：深青 `#0f3b3a`、米白 `#f3ead7`、朱砂 `#b8452f`，含纸纹、光束、窗格、角色剪影符号；无外部图片、无真人照片、无第三方素材。
- 2 个角色 SVG 与应用内头像均自制；页面首屏明确“合成 · 脱敏 / 离线生成 / 无外部素材”。
- 播放器读取 `/api/ip/media-manifest` 的真实 `shots[{startMs,endMs,svg,audio,srt,caption}]`，用 `<audio>` 主音轨驱动时间轴，按当前时间切 SVG、叠加字幕；支持播放/暂停/重播/静音、时间轴拖点、12 个缩略图跳转，结束显示“样片结束”。不自动播放，符合浏览器用户手势要求。

### 4.5 浏览器 Range 限制的处理（如实记录）

Python 标准库静态服务返回完整 WAV，**不支持 HTTP Range**；直接以 `/media/voice/ip_sample.wav` 作为 `audio.src` 时，Chromium 能从头播放，但设置 `currentTime` 会退回到开头，导致时间轴/缩略图跳转失效。

页面实际处理：`prepareAudioBlob()` 用 `fetch` 把主音轨读成 Blob，再用 `URL.createObjectURL` 赋给 `<audio>`；blob 源可正常 seek。实测 `currentTime=19.8` 后停在 19.8 秒、切到 SHOT 07；播放到 40.4 秒触发 `ended` 与“样片结束”。没有修改 `server.py` 或任何共享文件。若 fetch/Blob 不可用，JS 回退为直连 WAV 并提示“如跳转失败请用重播”。

---

## 5. API 实测输出

所有请求均打到自测实例 `http://127.0.0.1:8791`。完整响应已保存到 `C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch/ip-api-log.json`，摘要到 `.scratch/ip-api-summary.json`。

### 5.1 GET 端点

| 端点 | 状态 | 实测关键值 |
| --- | ---: | --- |
| `/api/ip/config` | 200 | module.ip、version 1.0.0、characters 2、beats 6、shots 12、reviewRules 9、licenseClauses 12、skus 6、totalMs 40400 |
| `/api/ip/characters` | 200 | count 2；远视 can 3 / cannot 3，远听 can 3 / cannot 3 |
| `/api/ip/story` | 200 | beats 6、shots 12、duration.totalMs 40400、ok true、时间轴连续 |
| `/api/ip/assets` | 200 | total 41、present 41、missing 0、scenes 12、voices 12、subtitles 12、characters 2、sampleRates [22050] |
| `/api/ip/media-manifest` | 200 | totalMs 40400、shots 12、master.durationMs 40400 / 22050 / 1ch / 12 cues / ok true、allAudioFits true、assetsOk true、warnings [] |
| `/api/ip/dashboard` | 200 | 2 角色 / 12 分镜 / 40.4s / 41 素材 / ready true（重置后 reviews 0、licenses 0） |
| `/api/ip/reviews` | 200 | 返回 reviews[]、count/total、verdicts、rules、samples（scenario 后有 2 条） |
| `/api/ip/licenses` | 200 | 返回草稿列表（scenario 后 1 份） |
| `/api/ip/derivatives` | 200 | count 6；全部 statusLabel“待授权”；notes 明示合成规格 |

`/api/ip/config` 的 `media` 实测：

```json
{
  "voiceName": "Microsoft Huihui Desktop",
  "masterAudio": "/media/voice/ip_sample.wav",
  "masterSrt": "/media/subtitles/ip_sample.srt",
  "minMs": 30000,
  "maxMs": 45000,
  "totalMs": 40400,
  "totalSeconds": 40.4,
  "durationOk": true,
  "shotCount": 12
}
```

`/api/ip/media-manifest` 的 `master` 实测：

```json
{
  "audio": "/media/voice/ip_sample.wav",
  "srt": "/media/subtitles/ip_sample.srt",
  "durationMs": 40400,
  "sampleRate": 22050,
  "channels": 1,
  "bytes": 1781684,
  "srtCues": 12,
  "ok": true
}
```

### 5.2 审核

合规样例（`config.review.samples.pass`）：

```bash
curl.exe -s -X POST http://127.0.0.1:8791/api/ip/review \
  -H "Content-Type: application/json" \
  --data "{\"text\":\"《山谷回声》为原创纸影短剧，角色、画面与配音均为自制；无真人扮演，无外部版权素材；已获授权用于合成样例演示。\",\"target\":\"端点验证 · 合规文案\",\"role\":\"admin\"}"
```

实测：HTTP 200，`verdict: pass`、`findings: []`、`reviewId: review-076ff6a2`、`reviewedAt: 2026-10-30T17:37:55+00:00`。

违规样例：

```bash
curl.exe -s -X POST http://127.0.0.1:8791/api/ip/review \
  -H "Content-Type: application/json" \
  --data "{\"text\":\"本片由真人扮演远视，并引用网络热曲；角色包治百病，能治失眠，保证收益。\",\"target\":\"端点验证 · 违规文案\",\"role\":\"admin\"}"
```

实测：HTTP 200，`verdict: reject`，命中 5 条：

```json
{
  "rules": ["real_person", "medical_claim", "commercial_overclaim", "adaptation", "copyright_statement"],
  "counts": {"blockers": 3, "majors": 1, "minors": 1}
}
```

短文案校验：HTTP **422**，`{ok:false, error:"text_too_short", message:"待审文案至少需要 4 个字符", length:1, minLength:4}`。

越权：role=workshop 提交合规文案，HTTP **403**：

```json
{
  "ok": false,
  "error": "forbidden",
  "message": "角色 外包制作（演示） 不能执行 内容审核",
  "capability": "content.review",
  "allowedRoles": ["ops", "admin"]
}
```

### 5.3 授权草稿与校验

```bash
curl.exe -s -X POST http://127.0.0.1:8791/api/ip/license/preview \
  -H "Content-Type: application/json" \
  --data "{\"licensee\":\"端点验证合成品牌（演示）\",\"purpose\":\"品牌短片\",\"territory\":\"中国大陆\",\"term\":12,\"role\":\"admin\"}"
```

实测：HTTP 200，`draftNo: IP-LIC-20261031-F082A846`、`clauseCount: 12`、`baseFee: 8,000.00 元`、`derivativeRoyalty: 8%`、`notice: 模板样例，不构成法律意见`。

非法期限 `term=0`：HTTP **422**，`{ok:false, error:"term_invalid", message:"授权期限需在 1–60 个月之间", term:0}`。
页面下拉提供 6/12/24/36 个月作为推荐选项；API 允许 1–60 的整数月数。

`POST /api/ip/assets/validate`（admin）：HTTP 200，41/41 存在、0 缺失；6 项硬校验 `scenes / voices / voice_slot / subtitles / characters / master_audio` 全部 `ok: true`。

### 5.4 全链路 scenario

`POST /api/ip/scenario` 实测 summary：

```json
{
  "steps": 16,
  "passed": 16,
  "expectedFailures": 2,
  "okSteps": 14,
  "unexpected": 0,
  "failed": 0,
  "durationOk": true,
  "reviewPass": "pass",
  "reviewReject": "reject",
  "licenseNo": "IP-LIC-20261031-0DB4D875"
}
```

16 步与证据：

| # | 步骤 | 结果 | 关键证据 |
| ---: | --- | --- | --- |
| 1 | 加载模块配置（双角色 / 12 格分镜 / 9 条审核规则） | 通过 | version 1.0.0、characters 2、beats 6、shots 12、rules 9 |
| 2 | 角色手册：设定、母题、声音画像、能与不能 | 通过 | 2 角色、各 3 条 can / 3 条 cannot |
| 3 | 剧本节拍：6 场覆盖 12 格分镜 | 通过 | 覆盖 1–12，6 个节拍 |
| 4 | 分镜表：逐格字段完整并含字幕台词 | 通过 | 12 格 × 13 字段，说话人旁白/远视/远听 |
| 5 | 时长校验：总时长落在 30–45 秒 | 通过 | 40,400 ms，min 30,000 / max 45,000 |
| 6 | 素材清单：SVG / WAV / SRT 全部存在 | 通过 | 41 / 41 存在，0 缺失；6 项检查通过 |
| 7 | 播放器 manifest：时间轴连续、总时长合规 | 通过 | 40.4s、12 段首尾相接、主音轨 40.4s、12 cue |
| 8 | 真实配音：12 段 WAV 均为 22.05kHz 且不超镜长 | 通过 | 12 段、22050Hz、总语音 35,791ms、逐段 fits |
| 9 | 字幕：12 段分镜 SRT + 12 条总字幕 | 通过 | 首条 00:00:00,000 → 00:00:03,080；主 SRT 937 bytes |
| 10 | 内容审核：合规文案通过并留痕 | 通过 | review-9c822c44、verdict pass |
| 11 | 内容审核：违规文案被拒绝并命中规则 | 通过 | review-4e4a7f1a、verdict reject、5 条规则 |
| 12 | 审核留痕：两次审核记录可查询 | 通过 | 2 条记录，pass + reject |
| 13 | 授权草稿：12 条条款与免责声明 | 通过 | 12 条、模板声明、被许可方/用途/区域替换 |
| 14 | 衍生品：6 个 SKU 规格与分成 | 通过 | 6 个，全部“待授权” |
| 15 | **越权被拒**：工坊角色不能执行内容审核 | **预期拦截** | HTTP 403、forbidden、allowedRoles ops/admin |
| 16 | **缺失 wav 报错**：故障注入 shot-01.wav 被校验拦截 | **预期拦截** | HTTP 422、asset_missing、media/voice/shot-01.wav |

### 5.5 重置

`POST /api/ip/demo/reset`（admin）：

```json
{
  "ok": true,
  "cleared": {"reviews": 2, "licenses": 1, "events": 3},
  "total": 6,
  "mediaUntouched": true
}
```

重置后立即读取 dashboard：`reviews.total=0, licenses=0, assets.missing=0, ready=true`。媒体文件不被删除；scenario 自检自身也会先 reset 再跑，因此可重复。

---

## 6. 前端与截图证据

| 截图 | 尺寸 / 字节 | 核验内容 |
| --- | --- | --- |
| `C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch/ip-first.png` | 1654×1507 / 746,492 | 首屏：标题、声明、8 个 KPI、双角色卡与 SVG 头像、播放器首帧、12 缩略图；角色卡 2、分镜表 12 行、素材表 41 行、SKU 6 行 |
| `.scratch/ip-player.png` | 1654×1507 / 932,330 | 播放到 SHOT 07、字幕叠加、暂停/重播/静音、00:20.9 / 00:40.4、时间轴游标、缩略图选中态 |
| `.scratch/ip-review.png` | 1654×1507 / 325,669 | 违规审核结果“拒绝”、5 条命中（3 blocker / 1 major / 1 minor）、审核留痕 3 条 |
| `.scratch/ip-scenario.png` | 1654×1507 / 348,405 | 全链路面板“16 / 16 步通过 · 2 预期失败”，16 条步骤证据，含 403 / 422 两条预期拦截 |
| `.scratch/ip-license.png` | 1654×1507 / 366,962 | 授权草稿：编号、12 条条款、免责声明、最近草稿历史、6 个 SKU 规格表 |
| `.scratch/ip-forbidden.png` | 1654×1507 / 372,576 | 角色切到“工坊”后，审核台显示“权限拦截 / HTTP 403 / 不能执行 内容审核”，权限提示同步更新 |

补充实测：

- 页面加载后 DOM：`characterCards=2`、`thumbs=12`、`shotRows=12`、`assetRows=41`、`skuRows=6`。
- 主音轨经 Blob 载入后 `duration=40.4`、`readyState=4`、`currentSrc=blob:http://127.0.0.1:8791/...`，播放说明为“音频已就绪 · 40.4 秒 · 点击播放（需用户手势，不自动播放）”。
- 点击缩略图 07：`currentTime=19.8`、stage 切到 `/media/scenes/shot-07.svg`、字幕“一线光，够点亮一整个窗口。”。
- 点击播放：`paused=false`，1 秒后 `currentTime=20.78`；点击时间轴 50%：`currentTime=20.95`；点击 99.6%：`currentTime=40.4`、`ended=true`、结束卡“END / 样片结束”。
- 页面重载后清空 CDP 日志再采集：`Runtime.exceptionThrown=0`、错误级 `Log.entryAdded=0`、错误级 `consoleAPICalled=0`。此前有一次故意请求 403 产生的历史资源日志，已在重载前清除，不属于页面脚本异常。
- 页面不存在自动播放：初始 `audio.paused=true`；播放必须由用户手势触发。

---

## 7. 验证记录表（命令 / 输入 / 期望 / 实际 / 复跑）

| # | 验证项 | 命令或输入 | 期望 | 实际 | 如何复跑 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 单元测试 | `python -m unittest tests.test_ip -v` | 14 用例全过 | `Ran 14 tests in 0.519s / OK` | 见 2.3 |
| 2 | 配置 | `GET /api/ip/config` | 200，2 角色/6 节拍/12 格/9 规则/12 条款/6 SKU | 全部匹配；totalMs 40400 | 浏览器或 curl |
| 3 | 分镜时长 | `GET /api/ip/story` | 总时长 30–45s、时间轴连续 | 40400ms、ok true | curl + jq/JSON 查看 duration |
| 4 | 素材 | `GET /api/ip/assets` | 41 项存在、0 缺失 | 41/41，missing [] | 见 2.2 后重启 |
| 5 | manifest | `GET /api/ip/media-manifest` | 12 镜、主音轨 40.4s、12 cues | 40400ms、22050Hz、1ch、12 cues、allAudioFits true | curl |
| 6 | 审核通过 | `POST /api/ip/review` 合规样例 | 200，pass，留痕 | review-076ff6a2，findings [] | 见 5.2 |
| 7 | 审核拒绝 | `POST /api/ip/review` 违规样例 | 200，reject，命中规则 | 5 条，blockers 3 / majors 1 / minors 1 | 见 5.2 |
| 8 | 文案过短 | 1 个字符 | 422 text_too_short | 422，length 1，minLength 4 | 见 5.2 |
| 9 | 越权 | role=workshop 调 review | 403 forbidden | 403，allowedRoles ops/admin | 见 5.2 |
| 10 | 授权草稿 | licensee + purpose + territory + term=12 | 12 条条款 + 免责声明 | IP-LIC-…A846，clauseCount 12，8,000 元 / 8% | 见 5.3 |
| 11 | 非法期限 | term=0 | 422 term_invalid | 422，1–60 个月提示 | 见 5.3 |
| 12 | 素材校验 | `POST /api/ip/assets/validate` | 6 项硬校验通过 | 全部 ok:true | 页面按钮或 curl |
| 13 | 全链路 | `POST /api/ip/scenario` | 16 步、2 预期失败、0 意外 | 16/16，expected 2，unexpected 0 | 见 2.4 |
| 14 | 重置 | `POST /api/ip/demo/reset` | 清空审核/授权，媒体保留 | cleared 2/1/3，mediaUntouched true，ready true | 页面按钮（需 admin） |
| 15 | 真实 WAV | `wave` 读取 12 段 + 主音轨 | 22,050Hz、逐段 ≤ 镜格、主 40.4s | 全部符合，见 4.2 | `scripts/gen_ip_assets.py` 后重新读取 |
| 16 | 页面与播放器 | Edge headless / CDP 交互 | 首屏、跳转、播放、结束卡、无 JS 异常 | 见第 6 节 | 打开 8791 页面；截图命令见下 |

截图复跑命令（Edge headless，需先启动 8791）：

```bash
"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1680,1600 --virtual-time-budget=8000 \
  --screenshot="C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch/ip-first.png" \
  http://127.0.0.1:8791/pages/ip.html
```

说明：本机 Edge 直接 `--screenshot` 有时异步落盘、`--dump-dom` 为空；本次交互截图改用 CDP `Page.captureScreenshot`，命令等价且更可靠。首屏静态截图的最终版由 CDP 在页面重载后截取。

---

## 8. 已知边界与未做项（如实）

1. **不是 MP4 视频文件**。播放器是“浏览器内时间轴合成”：真实 WAV 驱动、SVG 切帧、SRT 字幕叠加。没有 ffmpeg/外网，因此没有导出成片；这不影响页面内 30–45 秒样片可播放。
2. **TTS 依赖 Windows 本机语音**。使用 Microsoft Huihui Desktop；换机器/换语音、重新生成时，每段 WAV 的毫秒数会变化，主音轨仍会按分镜时长对齐。若机器没有中文语音，`make_voice.ps1` 会失败；`--no-voice` 仅用于跳过 TTS 重画图形/字幕。
3. **音频 seek 的 Blob 方案是浏览器兼容处理**。Python 标准库静态服务不支持 Range；页面 fetch 整段 WAV 成 Blob 后可 seek。若浏览器禁用 fetch/Blob，回退直连模式，跳转会退化为从当前位置重播。
4. **审核台是确定性关键词/否定词规则**，不是语义模型，也不构成法律或平台合规结论；它只覆盖演示所需 9 类风险，可能漏判反讽、谐音、图片内文字等。规则可继续在 JSON 中扩充。
5. **合同是模板样例，不构成法律意见，不产生真实授权效力**；没有真实被许可方、对价、签署、发票或争议解决安排。正式使用必须由执业律师审核。
6. **衍生品规格为合成样例**，无真实供应商、材料检测、报价、产能或上市商品；全部状态“待授权”。
7. **所有角色/故事/画面/声音均为原创或合成演示**，与真实非遗项目、真实工坊、真实客户无关；页面已持续标注“合成 · 脱敏”。
8. **scenario 会重置本模块台账**（这是为了可复跑），但不会删除媒体文件；重置只清 reviews/licenses/events。
9. **只在 Edge headless 实测**；未覆盖 Firefox/Safari、移动端窄屏、屏幕阅读器完整流程。CSS 有 1260px / 760px 断点，但未做真机回归。
10. **单机本地演示**：JsonStore/SQLite 无并发写入压测，无多用户会话隔离；不适合直接当生产内容审核或合同系统。
11. 首屏 KPI 显示 0 条审核 / 0 份授权是最后一次 reset 后的真实状态；跑一次“一键全链路自检”或提交审核后数字会更新，截图 `ip-review.png` / `ip-license.png` 记录了有数据的时刻。
12. 页面每次 scenario 自检都会重建 2 条审核 + 1 份草稿；历史记录不跨 reset 保留，这是演示设计。

---

## 9. 给 leader 的验收摘要

**做了什么（模块 C）**

- 双原创角色远视/远听的角色手册；6 节拍、12 格分镜的原创纸影短剧《山谷回声》。
- 真实离线媒体：Windows SAPI 中文配音 12 段 WAV、12 段分镜 SRT + 主 SRT、12 张自制场景 SVG、2 张角色 SVG、海报、40.4 秒主音轨；全部有实测时长与存在性校验。
- 浏览器内可播放样片：SVG 按 manifest 时间轴切场景 + 真实配音 + 字幕叠加 + 播放/暂停/重播/静音/时间轴/缩略图跳转/结束卡。
- 审核台（9 条规则 + 留痕）、12 条授权合同草稿模板、6 个衍生品 SKU 规格。
- 后端 `mod_ip.py`（GET 9 个端点 + POST 5 个端点）、页面 `pages/ip.html/js/css`、`tests/test_ip.py`、本验证文档。

**端点清单**

- GET：`/api/ip/config`、`/api/ip/characters`、`/api/ip/story`、`/api/ip/assets`、`/api/ip/media-manifest`、`/api/ip/dashboard`、`/api/ip/reviews`、`/api/ip/licenses`、`/api/ip/derivatives`
- POST：`/api/ip/review`、`/api/ip/license/preview`、`/api/ip/assets/validate`、`/api/ip/scenario`、`/api/ip/demo/reset`
- 约定：成功 `{ok:true,...}`；业务错误 4xx/422 `{ok:false,error,message}`；未捕获异常 `internal_error`；权限 403 `forbidden`；所有 POST 带 `role`，缺省 admin。

**验证结果**

- `tests/test_ip.py`：14/14 通过（临时数据目录，可重复）。
- `POST /api/ip/scenario`：16 步全部满足，14 步正常通过 + 2 步预期拦截（工坊越权 403、缺失 shot-01.wav 422），意外 0。
- 页面 CDP 实测：首屏 2 角色、12 分镜、41 素材、6 SKU；播放/跳转/结束/审核/合同/403 提示全部可用；重载后 0 JS 异常。
- 截图（`.scratch/`）：`ip-first.png`、`ip-player.png`、`ip-review.png`、`ip-scenario.png`、`ip-license.png`、`ip-forbidden.png`。
- 自测服务使用 8791，未触碰 8787；验证结束已停止。

**已知问题（不阻塞验收）**

1. 播放器是浏览器内 SVG/WAV/SRT 时间轴合成，不导出 MP4（无 ffmpeg）。
2. TTS 依赖本机 Huihui 语音；重新生成会使 WAV 毫秒数变化，总时长仍受 30–45 秒代码校验。
3. 因 Python 静态服务无 Range，音频用 Blob 载入实现 seek；已实测。
4. 审核规则与合同均为演示级，不构成法律意见/平台合规结论；SKU 为合成规格。
5. 只在 Edge headless 验证；未做 Firefox/Safari/移动端真机回归。

**结论**：模块 C 的“角色 → 剧本 → 分镜 → 自制视觉 → 真实配音/字幕 → 可播放样片 → 审核留痕 → 授权/衍生品 → 越权与素材故障”纵切已真实跑通，可复跑、可核验，未使用外部素材或外部模型。

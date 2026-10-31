# 翻译管线永久方案（语音 ASR + 文本翻译多后端）— 2026-10-30

状态：P0 实施中 ｜ 触发：手机 H5 翻译 TAB 语音识别事故 + 用户拍板接百度免费额度
关联：INDEX 决策 #2/#15、language_dual_system_design_2026-10-25.md、铁律 21/22

## 0. 背景：2026-10-30 事故复盘

手机语音输入链路（前端 25s 录音 → WAV → `POST /api/v1/asr` → AsrClient → 文本）当天两连挂：

1. **503 asr_not_configured**：两个 uvicorn 进程 2026-10-29 23:38 启动，早于 .env 修改（10-30 15:50），
   运行态 `glm_api_key=""` —— 进程未读到配置。修复=按标准流程重启双服务（taskkill PID → Start 任务）。
   **教训：改 .env 后必须重启服务；服务启动必须经计划任务 cmd（cd 到 `CHINATRIP CODES`）**。
2. **502 asr_error（上游 429）**：智谱返回 `{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}`
   —— `glm-asr-2512` 是付费模型，聊天/规划的 flash 模型可用但 ASR 需单独资源包。

用户拍板：语音识别接 **百度短语音识别（免费调用量）**，翻译管线做成 **可切换多后端** 的永久方案。
用户语言需求：**中文为主 + 英文，偶尔其它语言**。

## 1. 现状盘点（代码事实）

| 层 | 现状 |
|---|---|
| API | `app/api/asr.py`：multipart wav ≤25MB、X-Device-ID 校验；错误映射 503 未配置 / 502 AsrError / 504 超时 |
| 客户端 | `app/services/asr_client.py`：唯一实现 = 智谱 `open.bigmodel.cn/api/paas/v4/audio/transcriptions` |
| 配置 | `.env`：GLM_API_KEY/BASE_URL/MODEL；`asr_model` 默认 glm-asr-2512（config.py）；`BAIDU_AK` 为地图专用，勿混用 |
| 前端 | `index.html` 采样率 = AudioContext.sampleRate（手机通常 48000Hz），Float32 → 16bit 单声道 WAV，无重采样 |
| 文本翻译 | t9n 文字翻译走 zhipu flash 快车道（工作正常，本期不动） |

## 2. 目标与约束

- 语种：中英为主、其它语言渐进覆盖；单次录音 ≤25s（前端自动停）。
- 红线：CN 生产不依赖海外 API（铁律 21 语境）；**Key 永不进客户端**（同高德地图口径）；音频过服务端转发。
- 成本：免费优先 —— 百度短语音识别免费调用量（企业认证 10 万次/1 年，个人认证有少量免费额度）；
  长期可落 **本地开源 SenseVoice-small**（0 成本无限量，中英粤日韩 5 语种）。
- 永久性：后端可切换、兜底链清晰、降级提示明确、配置向后兼容（不配新键 = 现状行为）。

## 3. 架构设计

### 3.1 ASR 后端开关

```
ASR_BACKEND = zhipu（现状默认） | baidu（本次新增主用） | sensevoice（P1 预留，本地）
```

`AsrClient` 协议化：`api/asr.py` 依赖注入按 `ASR_BACKEND` 选择实现，API 层错误映射**不变**。

### 3.2 baidu 实现（P0）

- **access_token**：`GET https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id=<API_KEY>&client_secret=<SECRET_KEY>`
  进程内缓存（expires_in 约 30 天），过期重取；token 不落盘不进前端。
- **识别**：`POST https://vop.baidu.com/server_api`，JSON：
  `{format:"wav", rate:16000, channel:1, dev_pid:<配置>, speech:<base64>, len:<字节数>, token:<token>}`
  - `dev_pid` 默认 **1537（普通话带标点，支持简单英文）**；纯英文场景 1737；以官方 dev_pid 表为准（接入时核对）。
- **重采样（关键坑）**：百度要求 16000Hz，前端手机录出来通常是 48000Hz —— 服务端用
  **imageio-ffmpeg**（项目已随依赖自带 ffmpeg 二进制，config.py 有先例）统一 `-ar 16000 -ac 1` 转码后再提交；
  前端零改动，避免前端采样率兼容矩阵。
- **响应**：`{err_no:0, result:["文本"]}`；err_no≠0 → AsrError（3301 音质问题 / 3302 鉴权失败 /
  3303 服务忙 / 3304&429 类=用户超额，以官方错误码表为准，接入时核对）。
- 上限：60s / 次调用（我们 25s 录音，余量充足）。

### 3.3 文本翻译后端（P2 预留）

`TRANSLATE_BACKEND = zhipu（默认现状） | baidu_fanyi（翻译开放平台 通用翻译，标准版免费 QPS=1）`。
本期不动 —— t9n 文本翻译走 zhipu 正常工作。

## 4. 配置键（.env 增量，全部向后兼容）

```
ASR_BACKEND=baidu            # zhipu | baidu | sensevoice(预留)
BAIDU_ASR_API_KEY=...        # 语音技术应用详情页 API Key
BAIDU_ASR_SECRET_KEY=...     # 应用详情页 Secret Key
BAIDU_ASR_DEV_PID=1537       # 默认普通话带标点（支持简单英文）
TRANSLATE_BACKEND=zhipu      # zhipu | baidu_fanyi(预留)
BAIDU_FANYI_APPID=           # 预留（翻译开放平台）
BAIDU_FANYI_KEY=             # 预留
```

config.py `Settings` 增 `asr_backend / baidu_asr_api_key / baidu_asr_secret_key / baidu_asr_dev_pid`（默认空=旧行为）。

## 5. 实施阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | .env 双键 + baidu AsrClient 实现 + ASR_BACKEND 开关 + ffmpeg 16k 重采样 + probe_asr 复测 | 本次实施 |
| P1 | 本地 SenseVoice-small（funasr + CPU torch，模型 ~1GB），ASR_BACKEND=sensevoice，长期 0 成本 | 规划 |
| P2 | 文本翻译后端切换（百度翻译开放平台 免费额度） | 预留 |
| 回滚 | `ASR_BACKEND=zhipu`（或清空开关 = 现状），配置级回滚无代码回退 | — |

## 6. 验收标准

1. `probe_asr.py` 对 8000/8443 真实 POST：期望 `200 {"text": ...}`（不再是 503/502）。
2. 手机真机：中文短句、英文短句各一条，翻译 TAB 拿到正确文本并完成翻译。
3. 降级路径：未配 key=503、上游额度尽=502 明示「识别额度用尽」，前端 toast 可读。
4. pytest 全量绿（baidu 客户端用 fake transport 单测，无网络依赖）。

## 7. 风险与备注

- 百度免费额度随认证等级变化（本设计引用 2026-10-30 产品页口径），额度尽后 0.0034 元/次 —— 错误映射里体现。
- `dev_pid`/错误码细节以官方文档核对：https://cloud.baidu.com/doc/SPEECH/index.html
- 服务重启纪律（本次事故教训）：**改 .env 必须重启 uvicorn 双进程**；启动只走计划任务 cmd。
- 测试期 key 由用户申请提供；生产若换主体（企业认证），换 key 即可，代码不动。

## 8. 更正记录（2026-10-30 深夜）：真实接口 = 百度智能云 speech-translation

**517 事故根因修正**：语音翻译 API 的真实接口不在翻译开放平台（fanyi-api.baidu.com），
而在**百度智能云**：`https://aip.baidubce.com/rpc/2.0/mt/v2/speech-translation`（官方 MT.pdf 语音翻译章节，
doc/27 与本设计 §3.2 的 fanyi 网关口径全部作废——此前打到 fanyi 老网关返回 error_code 517 "Unknown Error Code"）。

### 8.1 官方规范（MT.pdf 40-41 页）

- 鉴权：URL 参数 `access_token` = API Key + Secret Key 经 `aip.baidubce.com/oauth/2.0/token`（client_credentials）换取；
  进程内缓存（expires_in 约 30 天，提前 60s 刷新）
- `POST {endpoint}?access_token=...`，`Content-Type: application/json`
  Body：`{from, to, voice(音频base64，编码后≤4MB), format(pcm|wav)}`
- 音频：≤60s（不含60秒）、16kHz/16bit/单声道；中文/粤语支持 pcm+wav，其它语种仅 pcm → 服务端统一转 PCM 16k
- 语种方向：中↔英、中/英→其它、其它→中/英（**不支持 auto 源语种**，需显式指定）
- 正常返回：`{log_id, result:{source(识别原文), target(译文), target_tts(译文MP3 base64，译文>400字节时不返回)}}`
- 异常返回：`{error_code, error_msg}`（BCE 风格）；此前 517 即 fanyi 老网关对未知路径的业务码

### 8.2 实施同步

- `BaiduVoiceTranslateClient` 重写：OAuth access_token 缓存 + JSON body + result.source/target 解析
- 凭据切换为**百度智能云应用**：`BAIDU_BCE_APPID=124589608` + `BAIDU_BCE_API_KEY`（用户已供）+ `BAIDU_BCE_SECRET_KEY`（待用户补）
- `.env`：`BAIDU_VT_FROM=zh`（auto 不支持）；fanyi 旧键（BAIDU_FANYI_APPID/KEY）留存不用
- 门禁：test_asr + test_asr_baidu_vt **19 passed**（OAuth 两跳 MockTransport：token 缓存/失败映射/业务错误映射/PCM 透传）、ruff 全绿


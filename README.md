# GLM Desk

`GLM Desk` 是一个本地运行的 `GLM Coding` 支付运营后台，用来管理多账号导入、套餐同步、自动验证码链路、预览下单、签单出二维码，以及定时启动任务。

当前页面已经不是早期的调试台，而是简约列表后台：

- 顶部弹窗导入账号
- 导入后自动同步账号上下文和套餐
- 每个账号单独选择套餐
- 每个账号单独配置定时启动时间
- 列表直接展示最新支付二维码和价格
- 点击账号名查看上下文
- 支持“同步并换指纹”
- 支持删除账号，并清理该账号本地缓存

## 功能概览

- 导入 `bigmodel_token_production`
- 自动调用 `getCustomerInfo`
- 自动补齐默认 `Organization / Project`
- 自动调用 `batch-preview` 获取套餐状态
- 后端拉取腾讯验证码图片
- 内置 OCR 识别点击点位
- 后端生成 `collect / eks / pow`
- 后端自动提交腾讯 `verify`
- `preview` 无 `bizId` 时自动重跑整条链路
- 新购走 `/biz/pay/create-sign`
- 升级走 `/biz/pay/product/update/sign`
- 签单失败先重试 `3` 次，失败后回到整条链路重新拿新 `bizId`
- 本地生成支付二维码
- 定时任务自动启动指定账号链路
- 服务启动时自动检查本地缓存账号是否有效
- 服务重启时自动清空旧二维码缓存

## 不包含

- 账号密码登录自动化
- `deviceToken`
- 浏览器页面端支付跳转逻辑
- 前端中间页 AES 协议复刻

## 环境要求

- Windows
- Python 3.12+
- Node.js 可用并在 `PATH` 中

说明：

- Python 用于 FastAPI 服务和 OCR
- Node.js 用于腾讯验证码 TDC VM 运行
- `start.bat` 首次启动会自动创建 `.venv` 并安装 Python 依赖

## 启动

1. 可选：复制 `.env.example` 为 `.env`
2. 双击 `start.bat`
3. 打开 `http://127.0.0.1:8787`

默认启动地址：

- `APP_HOST=127.0.0.1`
- `APP_PORT=8787`

## 启动进程与 OCR Worker 说明

本项目本地默认通过 [start.bat](E:/开源项目/glmDesk/start.bat) 启动：

- `uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --reload`

这意味着正常开发启动时通常会看到：

- `1` 个 `uvicorn` reload 监控进程
- `1` 个实际承载 FastAPI 的应用进程
- `N` 个 OCR 进程池 worker 上限，其中 `N = TENCENT_OCR_WORKERS`

说明：

- 项目没有配置 `uvicorn --workers`，所以 Web 服务本身不是多 worker 部署
- OCR 并发是独立进程池，不是 `uvicorn` worker
- 多账号调度是单应用进程里多线程拉任务，真正重 CPU 的 OCR 再交给 OCR 进程池
- 服务启动阶段会按 `.env` 中的 `TENCENT_OCR_WORKERS` 一次性预热全部 OCR worker，避免首轮支付链路临时 spawn worker 拖慢识别
- 支付链路启动前仍会按前端 `Preview 并发` 配置和当前活跃任务需求校验 OCR 容量，但不会超过 `TENCENT_OCR_WORKERS`
- 真正运行时 OCR 并发上限由 `TENCENT_OCR_WORKERS` 控制

`TENCENT_OCR_WORKERS` 是系统 OCR worker 最大数量，不配置时默认 `4`：

- `TENCENT_OCR_WORKERS=4`

举例：

- `Preview 并发=4` 且 `TENCENT_OCR_WORKERS=4`，服务启动时会直接预热 4 个 OCR worker
- 两个账号同时运行，账号 A `Preview 并发=3`，账号 B `Preview 并发=1`，活跃 OCR 需求为 `4`，服务启动后已经有 4 个 OCR worker 可用
- 如果活跃 OCR 需求为 `8`，但 `TENCENT_OCR_WORKERS=4`，仍然最多只跑 4 个 OCR worker，其余 OCR 请求排队

如果你想强制单路 OCR，直接把：

- `TENCENT_OCR_WORKERS=1`

写进 `.env` 就行。

## 动态代理与代理池

项目支持通过本地 `dynamic-proxy` 做代理轮换。`start.bat` 会在检测到 `dynamic-proxy/dynamic-proxy.exe` 时自动后台启动它。

### 启用方式

1. 构建或准备 `dynamic-proxy/dynamic-proxy.exe`：

```powershell
cd dynamic-proxy
go build -o dynamic-proxy.exe
```

2. 在 `.env` 中设置统一出口代理：

```env
FALLBACK_PROXY_URL=http://127.0.0.1:17286
```

端口含义：

- `http://127.0.0.1:17285`：HTTP strict，本地代理服务会验证上游 TLS
- `http://127.0.0.1:17286`：HTTP relaxed，本地代理服务不验证上游 TLS，兼容性更好
- `socks5://127.0.0.1:17283`：SOCKS5 strict
- `socks5://127.0.0.1:17284`：SOCKS5 relaxed

### 请求是否会走代理池

会，但前提是 `.env` 配的是本地 `dynamic-proxy` 监听地址，例如：

```env
FALLBACK_PROXY_URL=http://127.0.0.1:17286
```

实际链路是：

```text
GLM Desk 请求 -> FALLBACK_PROXY_URL -> dynamic-proxy -> 内存代理池 -> 上游代理 -> BigModel / Captcha
```

注意：`.env` 只决定 GLM Desk 是否把请求发给本地 `dynamic-proxy`，不直接读取 `good_proxies.txt`。`good_proxies.txt` 必须写进 `dynamic-proxy/config.yaml` 的 `proxy_list_urls`，才会被 `dynamic-proxy` 加载、健康检测并放入内存代理池。

如果某个账号单独配置了 `proxy_url`，则该账号优先使用自己的 `proxy_url`，不会使用 `FALLBACK_PROXY_URL`。

### 代理测试脚本

`dynamic-proxy/proxy_checker.py` 用于在启动前预筛选代理。它会对每个代理执行：

```text
TCP 握手 -> SOCKS5 协商 -> CONNECT 目标主机 -> TLS 握手
```

推荐先筛出可用代理，再让 `dynamic-proxy` 读取筛选结果：

```powershell
cd dynamic-proxy
python proxy_checker.py --from-config config.yaml --target www.bigmodel.cn:443 --max-latency 3000 --timeout 6 --concurrency 200 --output good_proxies.txt --show-errors
```

如果你已经有代理文件：

```powershell
cd dynamic-proxy
python proxy_checker.py --source proxies.txt --target www.bigmodel.cn:443 --max-latency 3000 --timeout 6 --concurrency 200 --output good_proxies.txt --show-errors
```

生成 `good_proxies.txt` 后，在 `dynamic-proxy/config.yaml` 中加入：

```yaml
proxy_list_urls:
  - "good_proxies.txt"
```

然后启动项目：

```powershell
start.bat
```

这样运行时才是：先用 `proxy_checker.py` 过滤出 `good_proxies.txt`，再由 `dynamic-proxy` 读取该文件并维护代理池，最后 GLM Desk 通过 `FALLBACK_PROXY_URL` 走这个代理池。

### 代理配置建议

- 目标是 `www.bigmodel.cn` 时，应使用国内可访问 BigModel 的代理源，不建议使用境外免费代理列表。
- `proxy_checker.py` 的 `--target` 应与 `dynamic-proxy/config.yaml` 中 `health_check.target` 保持一致。
- 免费代理波动很大，`good_proxies.txt` 只是当前时刻快照，正式运行前建议重新检测。
- 如果 `dynamic-proxy` 日志出现 `No proxy available`，说明内存代理池为空，需要检查 `config.yaml` 代理源、`good_proxies.txt` 路径或健康检测阈值。

## 页面使用

### 1. 导入账号

点击顶部 `导入账号`，填写：

- 账号备注
- Token

注意：

- 邀请码固定使用 `XOJGYOGNLN`
- 导入成功后会立刻执行：
  - 保存账号
  - 同步上下文
  - 获取套餐列表

### 2. 查看账号列表

列表页每行展示：

- 账号备注
- 购买模式：`新购 / 升级`
- 当前账号指纹 profile：例如 `chrome146 / chrome145 / edge146 / firefox149`
- 套餐下拉选择器
- 定时启动配置
- 账号状态
- 最新支付二维码
- 操作按钮

### 3. 切换套餐

每个账号的套餐用下拉框选择，切换后自动保存到本地会话。

### 4. 定时启动

每个账号都可以设置是否启用定时任务，以及启动时间。

默认时间：

- `09:59:58`

时间格式支持：

- `HH:MM`
- `HH:MM:SS`

实际保存时会统一格式化成 `HH:MM:SS`。

### 5. 立即启动

点击 `立即启动` 后，会立即执行该账号的完整支付链路：

1. 走验证码链路
2. 获取 `preview`
3. 签单
4. 生成二维码

### 6. 同步并换指纹

点击 `同步并换指纹` 后，会按“换指纹 -> 同步账号上下文 -> 同步套餐”的顺序执行。

如果同步失败，后端会继续换下一个指纹并重试，直到同步成功或达到最大重试次数。

默认最大重试次数：

- `BOOTSTRAP_FINGERPRINT_MAX_RETRIES=99`

这适合在上游风控、链路异常、套餐状态异常时主动切换一套新的网络指纹继续尝试。

### 7. 查看上下文

点击账号名，可以查看当前账号上下文，包括：

- `customerNumber`
- `customerName`
- 邀请码
- 账号状态
- 状态说明
- 定时配置
- 最近检查时间
- 完整账号 / 会话 JSON

### 8. 删除账号

点击 `删除账号` 后，会删除这个账号的本地数据。

当前删除范围包括：

- `accounts.json` 中该账号记录
- `tasks.json` 中该账号的二维码任务
- `data/sessions/{account_id}.json`
- `data/logs/` 中名字或内容带该 `account_id` 的文件 / 目录
- `data/test_runs/` 中名字或内容带该 `account_id` 的文件 / 目录

## 账号状态说明

页面状态列会展示两类状态：

### 账号状态

- `unchecked`：尚未检查
- `valid`：最近一次同步 / 启动检查成功
- `expired`：账号态不可用或凭据失效
- `error`：接口异常、系统繁忙、链路失败等

### 定时任务状态

- `running`
- `success`
- `failed`

说明：

- 手动同步失败时，账号状态会保留失败原因，不会再提前误写成 `valid`
- 服务启动后的自动检查如果成功，账号状态也会更新为最新结果

## 支付链路说明

### 购买模式判定

`/products` 这一步会根据 `batch-preview.isSubscribed` 给账号和套餐打标：

- `new_purchase`
- `upgrade`

后续二维码签单会按这个模式分流。

### 新购链路

使用：

- `/biz/pay/create-sign`

### 升级链路

使用：

- `/biz/pay/product/update/sign`

依赖 `preview.lastSubscriptionSummary` 中的：

- `productId`
- `agreementNo`

### 验证码重试策略

- OCR 点位少于 `3` 个，直接刷新验证码重新跑
- OCR 抛异常，也会刷新重跑
- `verify` 失败会回到整条验证码链路重新开始
- `preview` 没拿到 `bizId`，会无限重跑整条链路

### 二维码签单重试策略

拿到 `bizId` 后：

- 先对当前 `bizId` 重试签单 `3` 次
- 如果都失败：
  - 清空当前 `preview`
  - 重新走整条 `preview` 链路拿新 `bizId`
  - 再继续签单

## 指纹策略

`GLM Desk` 当前不是完整浏览器驱动，而是后端 HTTP 请求链路，所以做的是账号级稳定伪装：

- 每个账号首次导入时随机分配一个具体版本的 `browser_impersonate`
- 当前随机候选值为：`chrome146 / chrome145 / edge146 / firefox149`
- 随机分配带权重，默认更偏向 Chrome，少量分配 Edge / Firefox，贴近真实桌面浏览器分布
- 每个 profile 同时绑定 `curl-cffi` TLS/HTTP 指纹和匹配的 Windows 桌面 `User-Agent`
- 后续这个账号的 BigModel、腾讯验证码、TDC 请求都复用同一个 profile

这样做的目的：

- 保持同一账号整条链路的指纹一致
- 避免“每次请求随机换脸”导致风控更容易命中
- 避免新版 UA 搭配旧版 TLS 指纹这种很假的组合

浏览器版本说明：

- 2026-04-26 查询桌面浏览器版本占有率后，Chrome 侧优先使用高占比的 `145/146`
- Edge 侧使用 `edge146` 对应的 Windows UA；由于 `curl-cffi 0.15.0` 缺少新版 Edge TLS profile，transport 暂时复用同代 Chrome 146 指纹
- Firefox 侧使用 `firefox149` 对应的 Windows UA；由于 `curl-cffi 0.15.0` 支持的最新 Firefox transport 为 `firefox147`，底层 TLS 暂时落到 `firefox147`

## 本地数据目录

正式运行数据位于：

```text
data/
  accounts.json
  tasks.json
  sessions/
  logs/
    runtime/
  tdc_cache/
```

说明：

- `accounts.json`：账号主档
- `tasks.json`：最新二维码任务
- `sessions/`：账号上下文缓存
- `logs/`：运行日志
- `logs/runtime/`：正式运行日志
- `tdc_cache/`：腾讯 TDC 脚本缓存

## 正式运行日志

项目现在已经补了正式运行日志，不再只是控制台里飘几行 `INFO`。

日志目录：

```text
data/logs/runtime/
  app.log
  events-YYYY-MM-DD.jsonl
  accounts/
    {account_id}/
      YYYY-MM-DD.jsonl
```

说明：

- `app.log`：标准文本日志，适合直接翻看服务启动、异常栈、调度器运行情况
- `events-YYYY-MM-DD.jsonl`：当天全量结构化流水，适合排查整站任务
- `accounts/{account_id}/YYYY-MM-DD.jsonl`：单账号结构化流水，适合盯一个账号复盘

结构化日志核心字段：

- `timestamp`：事件时间
- `account_id`：账号 ID
- `run_id`：单次运行链路 ID，同一条链路会贯穿 `captcha -> preview -> sign`
- `action`：动作名称，比如 `run_payment_flow`、`bootstrap_account`
- `stage`：步骤名称，比如 `batch_preview`、`captcha_verify`、`preview`、`sign`
- `status`：步骤状态，比如 `started`、`success`、`retry`、`failed`、`paused`
- `details`：补充字段，包含 OCR 点位数、置信度、`bizId`、签单轮次等

当前正式日志会覆盖这些关键链路：

- 服务启动 / 停止
- OCR 预热
- 调度器启动、轮询异常、启动检查
- 账号导入、删除、同步并换指纹
- `getCustomerInfo`
- `/biz/pay/batch-preview`
- 验证码获取
- OCR 点位门禁判断
- 腾讯 `verify`
- `preview`
- `create-sign` / `update-sign`
- 二维码生成
- 支付状态检查
- 暂停、失败、重试

敏感字段处理：

- `token`
- `cookie`
- `ticket`
- `randstr`
- `sign`
- `collect / eks`
- base64 图片 / 二维码

这些字段进入结构化日志时会自动脱敏，不会原样落盘。

## 重启行为

服务每次启动时会做两件事：

1. 清空旧二维码缓存
2. 异步检查本地缓存账号是否有效

另外：

- 已生成的旧二维码不会跨重启保留
- 正式日志不会清空，会持续按天累积
- 日志保留天数默认 `7` 天，可通过 `RUNTIME_LOG_RETENTION_DAYS` 调整

这意味着：

- 页面不会沿用上一次生成的旧二维码
- 账号状态会在启动后自动更新

## 配置项

可选环境变量见 `.env.example`：

```env
APP_HOST=127.0.0.1
APP_PORT=8787
DATA_DIR=data
BIGMODEL_API_BASE=https://www.bigmodel.cn/api
BIGMODEL_ORIGIN=https://www.bigmodel.cn
BIGMODEL_REFERER=https://www.bigmodel.cn/glm-coding
BROWSER_IMPERSONATE=chrome146
BOOTSTRAP_FINGERPRINT_MAX_RETRIES=99
REQUEST_TIMEOUT_SECONDS=20
TICKET_POOL_START_JITTER_MS=0
TICKET_POOL_DRAIN_JITTER_MS=0
TICKET_POOL_DRAIN_MODE=serial
DEFAULT_LANGUAGE=zh-CN
TENCENT_CAPTCHA_DOMAIN=https://turing.captcha.qcloud.com
TENCENT_CAPTCHA_AID=196026326
TENCENT_CAPTCHA_ENTRY_URL=https://www.bigmodel.cn/glm-coding
TENCENT_CAPTCHA_MAX_RETRIES=3
TENCENT_CAPTCHA_MIN_CONFIDENCE=0.55
TENCENT_CAPTCHA_NODE=node
TENCENT_OCR_ENABLED=1
TENCENT_OCR_INCLUDE_DEBUG=0
TENCENT_OCR_WORKERS=4
TENCENT_OCR_TIMEOUT_SECONDS=6
TENCENT_OCR_OPENCV_THREADS=1
TENCENT_OCR_ONNX_THREADS=1
RUNTIME_LOG_LEVEL=INFO
RUNTIME_LOG_RETENTION_DAYS=7
```

布尔值参数支持：

- `1 / true / yes / on` 表示开启
- 其他值视为关闭

各参数含义如下：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `APP_HOST` | `127.0.0.1` | Web 服务监听地址，`start.bat` 会优先读取这个值来启动 `uvicorn` |
| `APP_PORT` | `8787` | Web 服务监听端口，`start.bat` 会先杀掉当前端口已占用进程再启动 |
| `DATA_DIR` | `data` | 本地数据目录，保存账号、会话、任务、日志、TDC 缓存；相对路径会按项目根目录解析 |
| `BIGMODEL_API_BASE` | `https://www.bigmodel.cn/api` | BigModel API 根地址 |
| `BIGMODEL_ORIGIN` | `https://www.bigmodel.cn` | BigModel 请求头 `Origin` 默认值 |
| `BIGMODEL_REFERER` | `https://www.bigmodel.cn/glm-coding` | BigModel 请求头 `Referer` 默认值 |
| `BROWSER_IMPERSONATE` | `chrome146` | 全局兜底浏览器指纹 profile；账号实际请求优先用账号自己的随机 `browser_impersonate` |
| `BOOTSTRAP_FINGERPRINT_MAX_RETRIES` | `99` | 点击“同步并换指纹”时的最大尝试次数；每轮先换一个账号级指纹，再完整同步上下文和套餐，失败才进入下一轮 |
| `REQUEST_TIMEOUT_SECONDS` | `20` | 上游 HTTP 请求超时时间，单位秒 |
| `TICKET_POOL_START_JITTER_MS` | `0` | ticket 池填满后、第一次 `/preview` 前的全局随机错峰上限，单位毫秒；账号级配置大于 `0` 时优先用账号级值 |
| `TICKET_POOL_DRAIN_JITTER_MS` | `0` | ticket 池每张 ticket 发射间隔的全局随机错峰上限，单位毫秒；串行模式是在两次 `/preview` 之间 sleep，并行模式是按累计随机延迟错峰提交 |
| `TICKET_POOL_DRAIN_MODE` | `serial` | ticket 池消耗模式：`serial` 为逐张串行请求，最稳；`parallel` 为错峰并行请求，谁先拿到 bizId 谁胜出，适合抢时间但更容易触发上游阈值 |
| `DEFAULT_LANGUAGE` | `zh-CN` | 默认请求语言，会写入 `Accept-Language` 和 `Set-Language` |
| `TENCENT_CAPTCHA_DOMAIN` | `https://turing.captcha.qcloud.com` | 腾讯验证码域名 |
| `TENCENT_CAPTCHA_AID` | `196026326` | 腾讯验证码业务 `aid` |
| `TENCENT_CAPTCHA_ENTRY_URL` | `https://www.bigmodel.cn/glm-coding` | 腾讯验证码 `entry_url` 和默认 `Referer` |
| `TENCENT_CAPTCHA_MAX_RETRIES` | `3` | 预留的验证码客户端最大重试次数配置，目前主链路重试逻辑由支付服务控制 |
| `TENCENT_CAPTCHA_MIN_CONFIDENCE` | `0.55` | OCR 点位门禁最低置信度，小于这个值会直接刷新验证码重跑 |
| `TENCENT_CAPTCHA_NODE` | `node` | 跑腾讯 TDC VM 时使用的 Node.js 命令 |
| `TENCENT_OCR_ENABLED` | `1` | 是否启用本地 OCR；关闭后自动识别不可用 |
| `TENCENT_OCR_INCLUDE_DEBUG` | `0` | 是否在 OCR 结果中附带调试图像 base64，开启后日志和响应会更重 |
| `TENCENT_OCR_WORKERS` | `4` | 系统 OCR worker 数量和最大并发；服务启动时会按该值一次性预热全部 worker |
| `TENCENT_OCR_TIMEOUT_SECONDS` | `6` | 单次 OCR worker 超时秒数 |
| `TENCENT_OCR_OPENCV_THREADS` | `1` | 每个 OCR worker 内 OpenCV 线程数，建议保持 `1`，避免多进程并发时线程爆炸 |
| `TENCENT_OCR_ONNX_THREADS` | `1` | 每个 OCR worker 内 ONNXRuntime 推理线程数，建议保持 `1`，多 worker 并发时更稳 |
| `RUNTIME_LOG_LEVEL` | `INFO` | 正式运行日志级别 |
| `RUNTIME_LOG_RETENTION_DAYS` | `7` | `app.log` 按天轮转保留天数 |

补充说明：

- `BROWSER_IMPERSONATE` 现在主要是全局兜底 profile 和 transport 展示值
- 真正运行时优先用账号自己的 `browser_impersonate`
- 账号级 `browser_impersonate` 在首次导入账号时随机分配为 `chrome146 / chrome145 / edge146 / firefox149`
- 历史账号里的 `chrome / edge / firefox / chrome124 / chrome136 / firefox137 / firefox147` 会自动映射到当前支持的具体 profile
- `BOOTSTRAP_FINGERPRINT_MAX_RETRIES` 小于 `1` 时会自动按 `1` 处理，避免配置错误导致完全不尝试
- 如果你把 `TENCENT_OCR_WORKERS` 配得太高，OCR 并发会更猛，但内存占用也会跟着往上窜，别一上来就梭哈
- ticket 池默认 `TICKET_POOL_DRAIN_MODE=serial`，这是为了避开 WAF 瞬时阈值；如果改成 `parallel`，建议同时配置 `TICKET_POOL_DRAIN_JITTER_MS` 做错峰，比如 `300~1000`，别又一把梭把 WAF 打醒

## 已知说明

- 上游 `batch-preview`、`create-sign`、`update/sign` 偶发会返回 `555 / 系统繁忙`
- 页面里的错误提示和账号状态会保留最近一次失败原因，方便复盘
- 正式页面不会单独落盘二维码 PNG 文件，只在 `tasks.json` 中保存 `qr_base64`

## 关键文档

- `glm-coding-new-purchase-field-map.md`
- `glm-coding-new-purchase-detailed-spec.md`
- `glm-coding-tencent-captcha-verify.md`

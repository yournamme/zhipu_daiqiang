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
NETWORK_EGRESS_MODE=dynamic_proxy
FALLBACK_PROXY_URL=http://127.0.0.1:17286
FALLBACK_PROXY_TICKET_POOL_ONLY=0
```

`NETWORK_EGRESS_MODE` 是启动默认出口模式，支持 `local`、`dynamic_proxy`。Web 端右上角可以运行时切换出口模式，切换后不需要重启服务；`.env` 只负责预先放好动态代理需要的地址。

只有配置了 `FALLBACK_PROXY_URL`，GLM Desk 才能切到动态代理模式。`start.bat` 也只会在 `FALLBACK_PROXY_URL` 指向本地 `dynamic-proxy` 端口（例如 `127.0.0.1:17286`）时启动 `dynamic-proxy`；如果该值为空，则动态代理模式不可用，`PROXY_WHITEIP_*` 和 `PROXY_POOL_*` 参数不会参与主链路。

如果只希望 ticket 池消耗阶段的 `/preview` 使用代理池，后续生成二维码、查询支付状态、验证码 challenge/verify 等流程走本地网络，可以开启：

```env
FALLBACK_PROXY_TICKET_POOL_ONLY=1
```

该开关只限制动态代理模式下 `.env` 中的 `FALLBACK_PROXY_URL` 兜底代理；只有 Web 端当前处于 `动态代理` 模式时，账号级 `proxy_url` 才会优先生效。

Web 端切到 `本地` 模式时，会强制走本机出口，不使用 `.env` 中的 `FALLBACK_PROXY_URL`，也不会使用账号级 `proxy_url`。这个模式适合排查本地网络和上游接口状态。

如果你的代理池服务商要求先添加出口 IP 白名单，可以让 `dynamic-proxy` 启动时自动调用白名单接口，再拉取代理池：

```env
PROXY_WHITEIP_ENABLED=1
PROXY_WHITEIP_SECRET_ID=your_secret_id
PROXY_WHITEIP_SECRET_KEY=your_secret_key
PROXY_WHITEIP_SECRET_TOKEN_API=
PROXY_WHITEIP_SIGN_TYPE=token
PROXY_WHITEIP_SIGNATURE=
PROXY_WHITEIP_API=
PROXY_WHITEIP_LIST=
PROXY_WHITEIP_WAIT_SECONDS=5
PROXY_POOL_MAX_LATENCY_MS=3000
PROXY_POOL_FAST_WINDOW=32
PROXY_POOL_FAILURE_COOLDOWN_SECONDS=60
```

启动时会先用 `PROXY_WHITEIP_SECRET_ID` + `PROXY_WHITEIP_SECRET_KEY` 调用 `PROXY_WHITEIP_SECRET_TOKEN_API` 获取动态 `secret_token`，再按 `PROXY_WHITEIP_SIGN_TYPE` 调用 `PROXY_WHITEIP_API`。如果你的服务商直接提供固定签名令牌，也可以留空 `PROXY_WHITEIP_SECRET_KEY` 和 `PROXY_WHITEIP_SECRET_TOKEN_API`，只填写 `PROXY_WHITEIP_SIGNATURE`。

`PROXY_WHITEIP_LIST` 留空时，由代理服务商接口自行识别当前出口 IP；如果要显式指定多个 IP，按你的服务商接口要求填写。`PROXY_WHITEIP_WAIT_SECONDS` 用来控制白名单接口调用后的等待时间，白名单接口失败不会阻断 GLM Desk 主服务启动，但 `dynamic-proxy` 日志会记录 `[ProxyWhiteIP]` 开头的错误，后续代理池拉取可能因为白名单未生效而失败。

端口含义：

- `http://127.0.0.1:17285`：HTTP strict，本地代理服务会验证上游 TLS
- `http://127.0.0.1:17286`：HTTP relaxed，本地代理服务不验证上游 TLS，兼容性更好
- `socks5://127.0.0.1:17283`：SOCKS5 strict
- `socks5://127.0.0.1:17284`：SOCKS5 relaxed

### 请求是否会走代理池

会，但前提是 `.env` 配的是本地 `dynamic-proxy` 监听地址，例如：

```env
FALLBACK_PROXY_URL=http://127.0.0.1:17286
FALLBACK_PROXY_TICKET_POOL_ONLY=0
```

实际链路是：

```text
GLM Desk 请求 -> FALLBACK_PROXY_URL -> dynamic-proxy -> 内存代理池 -> 上游代理 -> BigModel / Captcha
```

注意：`.env` 只决定 GLM Desk 是否把请求发给本地 `dynamic-proxy`，不直接读取 `good_proxies.txt`。`good_proxies.txt` 必须写进 `dynamic-proxy/config.yaml` 的 `proxy_list_urls`，才会被 `dynamic-proxy` 加载、健康检测并放入内存代理池。

如果当前处于 `动态代理` 模式，并且某个账号单独配置了 `proxy_url`，则该账号优先使用自己的 `proxy_url`，不会使用 `FALLBACK_PROXY_URL`。如果 Web 端切到 `本地`，账号级 `proxy_url` 不参与请求。

如果 `FALLBACK_PROXY_TICKET_POOL_ONLY=1`，`FALLBACK_PROXY_URL` 只会用于 ticket 池 drain 阶段提交 `/biz/pay/preview`。这个模式适合代理池 IP 时效性较短的场景：并发抢 `bizId` 时借助代理池分摊出口，拿到 `bizId` 后的创建支付二维码等后续请求回到本地出口，避免代理过期拖垮后半段链路。

如果 ticket 池全部发射完仍未拿到 `bizId`，系统会切回普通 preview 竞速重试链路；在 `FALLBACK_PROXY_TICKET_POOL_ONLY=1` 时，这个重试链路同样不会再使用 `FALLBACK_PROXY_URL`，而是走本地出口。

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

`dynamic-proxy` 每次启动和定时刷新代理池时都会重新健康检测代理，并按 TLS 连接耗时从快到慢排序。业务请求会从延迟最低的代理开始轮询，日志里会输出 `Latency sorted`，包含最快、最慢和平均耗时，方便判断代理池质量。

代理池调度可以通过 `.env` 控制：`PROXY_POOL_MAX_LATENCY_MS` 会在健康检测后丢弃超过阈值的慢代理；`PROXY_POOL_FAST_WINDOW` 会让运行时只在最快前 N 个代理里轮询；`PROXY_POOL_FAILURE_COOLDOWN_SECONDS` 会在某个代理连接失败或超时后临时冷却，避免继续把请求分给明显有问题的出口。

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
- 邀请码：默认 `XOJGYOGNLN`，如需使用自己的邀请码可直接覆盖

注意：

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
- Ticket 池大小和发射间隔
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

Ticket 池发射间隔在 Web 端按账号设置，不再通过 `.env` 配置：

- `0ms`：并行发射所有未使用 ticket 的 `/preview` 请求，谁先拿到 `bizId` 谁胜出
- 大于 `0ms`：按固定间隔串行发射，例如 `300` 表示两次 `/preview` 之间间隔约 `300ms`

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
NETWORK_EGRESS_MODE=local
DEFAULT_LANGUAGE=zh
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
TENCENT_OCR_IDLE_SHRINK_SECONDS=60
RUNTIME_LOG_LEVEL=INFO
RUNTIME_LOG_RETENTION_DAYS=7
FALLBACK_PROXY_URL=
FALLBACK_PROXY_TICKET_POOL_ONLY=0
PROXY_WHITEIP_ENABLED=0
PROXY_WHITEIP_SECRET_ID=
PROXY_WHITEIP_SECRET_KEY=
PROXY_WHITEIP_SECRET_TOKEN_API=
PROXY_WHITEIP_SIGN_TYPE=token
PROXY_WHITEIP_SIGNATURE=
PROXY_WHITEIP_API=
PROXY_WHITEIP_LIST=
PROXY_WHITEIP_WAIT_SECONDS=5
PROXY_POOL_MAX_LATENCY_MS=3000
PROXY_POOL_FAST_WINDOW=32
PROXY_POOL_FAILURE_COOLDOWN_SECONDS=60
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
| `NETWORK_EGRESS_MODE` | `local` | 启动默认出口模式，只支持 `local` 和 `dynamic_proxy`；运行中也可在 Web 端切换 |
| `FALLBACK_PROXY_URL` | 空 | 动态代理模式使用的代理池入口，例如 `http://127.0.0.1:17286` |
| `FALLBACK_PROXY_TICKET_POOL_ONLY` | `0` | 为 `1` 时，动态代理只用于 ticket 池 drain 阶段的 `/preview` |
| `DEFAULT_LANGUAGE` | `zh` | 默认请求语言，会写入 `Accept-Language` 和 `Set-Language` |
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
| `TENCENT_OCR_IDLE_SHRINK_SECONDS` | `60` | OCR worker 空闲收缩时间，当前作为预留配置保留 |
| `RUNTIME_LOG_LEVEL` | `INFO` | 正式运行日志级别 |
| `RUNTIME_LOG_RETENTION_DAYS` | `7` | `app.log` 按天轮转保留天数 |
| `PROXY_WHITEIP_ENABLED` | `0` | 是否启用代理服务商白名单接口；开启后 `dynamic-proxy` 启动时会尝试添加当前出口 IP |
| `PROXY_WHITEIP_SECRET_ID` | 空 | 代理服务商 API 身份 ID；不用白名单接口时留空 |
| `PROXY_WHITEIP_SECRET_KEY` | 空 | 代理服务商 API 密钥；不用动态令牌接口时留空 |
| `PROXY_WHITEIP_SECRET_TOKEN_API` | 空 | 代理服务商动态令牌接口地址；仅在服务商需要先用密钥换取令牌时填写 |
| `PROXY_WHITEIP_SIGN_TYPE` | `token` | 代理服务商签名方式，按自己的代理服务商文档填写 |
| `PROXY_WHITEIP_SIGNATURE` | 空 | 代理服务商签名令牌；如果使用密钥自动换取令牌，可留空 |
| `PROXY_WHITEIP_API` | 空 | 代理服务商白名单接口地址，模板不预设外部网站 |
| `PROXY_WHITEIP_LIST` | 空 | 需要加入白名单的 IP 列表；留空时由代理服务商接口自行识别当前出口 IP |
| `PROXY_WHITEIP_WAIT_SECONDS` | `5` | 调用白名单接口后等待代理池生效的时间，单位秒 |
| `PROXY_POOL_MAX_LATENCY_MS` | `3000` | 代理健康检测后的最大允许延迟，单位毫秒；超过该值的代理会被丢弃 |
| `PROXY_POOL_FAST_WINDOW` | `32` | 运行时只在延迟排序最靠前的 N 个代理内轮询；小于 `1` 时不限制窗口 |
| `PROXY_POOL_FAILURE_COOLDOWN_SECONDS` | `60` | 某个代理连接失败后的冷却时间，单位秒；冷却期内不再分配请求给该代理 |

补充说明：

- `BROWSER_IMPERSONATE` 现在主要是全局兜底 profile 和 transport 展示值
- 真正运行时优先用账号自己的 `browser_impersonate`
- 账号级 `browser_impersonate` 在首次导入账号时随机分配为 `chrome146 / chrome145 / edge146 / firefox149`
- 历史账号里的 `chrome / edge / firefox / chrome124 / chrome136 / firefox137 / firefox147` 会自动映射到当前支持的具体 profile
- `BOOTSTRAP_FINGERPRINT_MAX_RETRIES` 小于 `1` 时会自动按 `1` 处理，避免配置错误导致完全不尝试
- 如果你把 `TENCENT_OCR_WORKERS` 配得太高，OCR 并发会更猛，但内存占用也会跟着往上窜，别一上来就梭哈
- ticket 池发射间隔不再读取 `.env`，在 Web 端按账号设置；`0ms` 并行，大于 `0ms` 串行

## 已知说明

- 上游 `batch-preview`、`create-sign`、`update/sign` 偶发会返回 `555 / 系统繁忙`
- 页面里的错误提示和账号状态会保留最近一次失败原因，方便复盘
- 正式页面不会单独落盘二维码 PNG 文件，只在 `tasks.json` 中保存 `qr_base64`

## 关键文档

- `glm-coding-new-purchase-field-map.md`
- `glm-coding-new-purchase-detailed-spec.md`
- `glm-coding-tencent-captcha-verify.md`

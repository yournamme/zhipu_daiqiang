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
- 当前账号指纹伪装：`chrome / edge / firefox`
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

点击 `同步并换指纹` 后，会先给该账号分配一个新的账号级伪装指纹，再重新同步账号上下文和套餐。

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

- 每个账号首次导入时随机分配一个 `browser_impersonate`
- 候选值为：`chrome / edge / firefox`
- 后续这个账号的 BigModel、腾讯验证码、TDC 请求都复用同一个伪装

这样做的目的：

- 保持同一账号整条链路的指纹一致
- 避免“每次请求随机换脸”导致风控更容易命中

## 本地数据目录

正式运行数据位于：

```text
data/
  accounts.json
  tasks.json
  sessions/
  logs/
  tdc_cache/
```

说明：

- `accounts.json`：账号主档
- `tasks.json`：最新二维码任务
- `sessions/`：账号上下文缓存
- `logs/`：运行日志
- `tdc_cache/`：腾讯 TDC 脚本缓存

## 重启行为

服务每次启动时会做两件事：

1. 清空旧二维码缓存
2. 异步检查本地缓存账号是否有效

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
BROWSER_IMPERSONATE=chrome124
REQUEST_TIMEOUT_SECONDS=20
DEFAULT_LANGUAGE=zh-CN
TENCENT_CAPTCHA_DOMAIN=https://turing.captcha.qcloud.com
TENCENT_CAPTCHA_AID=196026326
TENCENT_CAPTCHA_ENTRY_URL=https://www.bigmodel.cn/glm-coding
TENCENT_CAPTCHA_MAX_RETRIES=3
TENCENT_CAPTCHA_MIN_CONFIDENCE=0.55
TENCENT_CAPTCHA_NODE=node
TENCENT_OCR_ENABLED=1
TENCENT_OCR_INCLUDE_DEBUG=0
```

说明：

- `BROWSER_IMPERSONATE` 现在主要作为全局兜底值
- 真正运行时优先用账号自己的 `browser_impersonate`

## 已知说明

- 上游 `batch-preview`、`create-sign`、`update/sign` 偶发会返回 `555 / 系统繁忙`
- 页面里的错误提示和账号状态会保留最近一次失败原因，方便复盘
- 正式页面不会单独落盘二维码 PNG 文件，只在 `tasks.json` 中保存 `qr_base64`

## 关键文档

- `glm-coding-new-purchase-field-map.md`
- `glm-coding-new-purchase-detailed-spec.md`
- `glm-coding-tencent-captcha-verify.md`

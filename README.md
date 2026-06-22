# AegisFlow - GLM Coding Plan 抢购工具

`AegisFlow` 是一个本地运行的智谱 GLM Coding Plan 支付运营后台，支持多账号管理、自动验证码识别、代理池轮换、定时抢购。

基于 [VitoHowe/glm-coding](https://github.com/VitoHowe/glm-coding) 二次开发，新增了快代理集成、Preview 并发升级、一键拉取/测试脚本等抢购优化功能。

## 功能特性

- **多账号管理**：导入多个智谱账号，自动同步套餐信息
- **自动验证码**：内置 OCR + TDC + POW，自动破解腾讯验证码
- **Preview 竞速**：支持 1-12 路并发抢 preview（原版最高 4 路）
- **代理池集成**：内置 Python 代理池，支持快代理等第三方代理源
- **定时抢购**：精确到秒的定时启动（建议 09:59:58）
- **支付二维码**：自动生成支付宝/微信二维码，扫码即付

## 快速开始

### 环境要求

- Windows 10/11（推荐）或 macOS
- Python 3.13（标准版，非 free-threaded 版）
- Node.js 18+
- 网络能访问 `bigmodel.cn`

### 安装步骤

1. **克隆仓库**

```bash
git clone https://github.com/yournamme/zhipu_daiqiang.git
cd zhipu_daiqiang
```

2. **首次启动**

双击 `start.bat`（Windows）或运行 `./start.sh`（macOS）。

脚本会自动完成：
- 创建 Python 虚拟环境
- 安装所有依赖
- 构建前端
- 启动 FastAPI 服务

3. **打开后台**

浏览器访问 http://127.0.0.1:8787

### 获取账号 Token

1. 浏览器登录 https://bigmodel.cn
2. F12 打开开发者工具 → Application → Cookies
3. 找到 `bigmodel_token_production`，复制它的值
4. 在 AegisFlow 页面点击「导入账号」，粘贴 token

## 代理池配置（可选，强烈推荐）

抢购时单 IP 容易被限流，配置代理池可以大幅提升成功率。

### 方案：快代理私密代理 + 本地代理池

本仓库集成了快代理 API 自动拉取脚本，支持 HMAC-SHA1 签名认证。

#### 1. 购买快代理私密代理

前往 https://www.kuaidaili.com 购买「私密代理」短效版（按量计费）。

- 推荐配置：标准版、1-5分钟有效、按量付费
- 1000 个 IP 约 9 元，够用 20 次抢购

#### 2. 配置密钥

在项目根目录创建 `.env` 文件：

```env
# 快代理订单 API 密钥（从 https://www.kuaidaili.com/uc/api/secret/ 获取）
KUAIDAILI_SECRET_ID=你的SecretId（20位）
KUAIDAILI_SECRET_KEY=你的SecretKey（32位）

# AegisFlow 配置
NETWORK_EGRESS_MODE=local
FALLBACK_PROXY_URL=http://127.0.0.1:17286
FALLBACK_PROXY_TICKET_POOL_ONLY=1
TENCENT_OCR_WORKERS=8
```

> ⚠️ `.env` 文件已被 `.gitignore` 忽略，不会上传到 Git。

#### 3. 修改代理池配置

`proxy_pool.yaml` 默认配置：

```yaml
proxy_list_urls:
  - "proxies.txt"        # refresh_kuaidaili.py 写入的代理文件

update_interval_minutes: 1  # 代理池每分钟刷新一次

health_check:
  target: "www.bigmodel.cn:443"

ports:
  http_relaxed: ":17286"    # AegisFlow 使用的入口端口
```

#### 4. 抢购前拉取代理

双击 `manual_refresh_proxy.bat`，或用定时任务自动拉取。

详细配置见下方「脚本说明」。

## 脚本说明

| 脚本 | 用途 | 消耗 IP |
|---|---|---|
| `start.bat` | 启动主服务 | 无 |
| `manual_refresh_proxy.bat` | 手动拉取 50 个新鲜代理 | 50 个 |
| `setup_proxy_refresh.bat` | 设定定时自动拉取（一次性） | 50 个 |
| `test_proxy.bat` | 测试当前代理可用性 | 无 |

### refresh_kuaidaili.py

核心拉取脚本，功能：
- 用 HMAC-SHA1 数字签名调用快代理 API（永不过期）
- 自动获取代理鉴权信息（用户名+密码）
- 写入 `proxies.txt` 供代理池读取

```bash
# 手动运行
.venv\Scripts\python.exe refresh_kuaidaili.py

# 修改拉取数量（默认50）
.venv\Scripts\python.exe refresh_kuaidaili.py --help
```

## 抢购操作流程

### 抢购当天

| 时间 | 操作 | 方式 |
|---|---|---|
| 09:40 | 双击 `start.bat` 启动服务 | 手动 |
| 09:50 | Web 配置账号/套餐/定时启动 09:59:58 → 切「代理池」模式 | 手动 |
| 09:57 | 自动拉取 50 个新鲜代理 | 自动 |
| 09:58 | 确认 Web 可用代理数 > 30 | 确认 |
| 09:59:58 | 自动触发抢购 → 扫码付款 | 自动 |

### 定时拉取设置

```powershell
# 创建明天 09:57 的一次性定时任务
schtasks /create /tn "AegisFlowProxyRefreshOnce" /tr "项目路径\.venv\Scripts\python.exe 项目路径\refresh_kuaidaili.py" /sc once /st 09:57 /sd 2026/06/23 /f

# 查看任务
schtasks /query /tn "AegisFlowProxyRefreshOnce"

# 删除任务
schtasks /delete /tn "AegisFlowProxyRefreshOnce" /f
```

## 配置项说明

### .env 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `KUAIDAILI_SECRET_ID` | 快代理订单 SecretId | 无（必填） |
| `KUAIDAILI_SECRET_KEY` | 快代理订单 SecretKey | 无（必填） |
| `NETWORK_EGRESS_MODE` | 出口模式：`local` / `proxy_pool` | `local` |
| `FALLBACK_PROXY_URL` | 代理池入口地址 | `http://127.0.0.1:17286` |
| `FALLBACK_PROXY_TICKET_POOL_ONLY` | 仅 ticket 池阶段走代理池 | `1` |
| `TENCENT_OCR_WORKERS` | OCR worker 数量（建议=preview并发） | `4` |

### Preview 并发

Web 页面每个账号可设置 Preview 并发（1-12）。

- 建议：8 路（兼顾成功率和服务器压力）
- OCR workers 需 ≥ Preview 并发，否则 OCR 成瓶颈

## 支付链路

```
导入 token → getCustomerInfo → batch-preview（拉套餐）
                                    ↓
定时触发 → 验证码(OCR+TDC+POW+verify) → preview（拿 bizId）
                                    ↓
                              create-sign（拿 sign）
                                    ↓
                              生成支付二维码 → 用户扫码
```

- 支付方式：支付宝（ALI）/ 微信（WE_CHAT）
- 余额自动抵扣，但必须扫码完成支付
- 一个身份证可实名多个智谱账号

## 代理池端口

| 端口 | 协议 | 说明 |
|---|---|---|
| 17286 | HTTP relaxed | **推荐使用**，兼容性最好 |
| 17285 | HTTP strict | 验证上游 TLS |
| 17284 | SOCKS5 relaxed | |
| 17283 | SOCKS5 strict | |

## 排错指南

| 问题 | 原因 | 解决 |
|---|---|---|
| `CFFI does not support free-threaded build` | Python 选了 3.13t（no-GIL 版） | `start.bat` 里用 `py -3.13` 指定标准版 |
| 导入账号后无套餐数据 | `import_account` 没调 `bootstrap_account` | 已修复，自动同步 |
| 代理池显示「no proxies fetched」 | `proxies.txt` 不存在或为空 | 运行 `manual_refresh_proxy.bat` |
| 代理连接返回 407 | 快代理需要鉴权信息 | 已修复，`f_auth=1` 获取用户名密码 |
| preview 持续 555 | 智谱服务器过载 | 非工具问题，只能等 |
| 代理池显示可用但实际失效 | 健康检查只测 TCP 不测业务 | 抢购前重新拉取新鲜代理 |

## 套餐信息

| 套餐 | 产品 ID | 价格 |
|---|---|---|
| Pro 月卡 | `product-1df3e1` | ¥149 |
| Max 月卡 | `product-2fc421` | ¥469 |

## 技术栈

- **后端**：FastAPI + curl-cffi + RapidOCR + onnxruntime
- **前端**：Vue 3 + Naive UI + Vite
- **验证码**：TDC VM（Node.js）+ 腾讯验证码逆向
- **代理池**：内置 Python 代理池服务

## 致谢

- 原项目：[VitoHowe/glm-coding](https://github.com/VitoHowe/glm-coding)

## 免责声明

本工具仅供学习和研究使用。使用者需遵守智谱 BigModel 的服务条款，自行承担使用风险。作者不对因使用本工具而产生的任何直接或间接损失负责。

抢购有风险，下单需谨慎。

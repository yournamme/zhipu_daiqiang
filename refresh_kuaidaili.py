#!/usr/bin/env python3
"""
快代理代理池手动/一次性刷新脚本（hmacsha1 签名方式）

功能：
  1. 用 HMAC-SHA1 数字签名调用快代理 API 拉取私密代理
  2. 覆盖写入 proxies.txt
  3. AegisFlow 代理池服务会定期读取 proxies.txt 并进行健康检查筛选

用法：
  手动运行一次：
    .venv\\Scripts\\python.exe refresh_kuaidaili.py

  在指定时间自动运行一次：
    双击 setup_proxy_refresh.bat，创建一次性 Windows 计划任务

  注意：不要创建周期性计划任务；每次提取都会消耗 50 个 IP 额度。

安全说明：
  - 密钥从环境变量读取，不硬编码在脚本里
  - 在 .env 文件中配置 KUAIDAILI_SECRET_ID 和 KUAIDAILI_SECRET_KEY
  - .env 文件已被 .gitignore 忽略，不会提交到 Git

依赖：
  - 只用标准库，无需额外安装
"""

import base64
import hashlib
import hmac
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# ============ 配置 ============
PROJECT_ROOT = Path(__file__).parent
PROXIES_FILE = PROJECT_ROOT / "proxies.txt"
ENV_FILE = PROJECT_ROOT / ".env"

# 快代理 API 配置
KDL_API_HOST = "dps.kdlapi.com"
KDL_API_PATH = "/api/getdps"
FETCH_NUM = 50  # 每次拉取数量（代理有效期 1-5 分钟，50 个够用）

# ⚠️ 重要：每次运行消耗 50 个 IP 额度！
# 你总共买了 1000 个 IP，也就是只能运行 20 次。
# 不要开着定时任务一直跑！只在抢购前手动运行一次。


def load_env():
    """从 .env 文件加载环境变量"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_credentials():
    """从环境变量获取快代理密钥"""
    secret_id = os.environ.get("KUAIDAILI_SECRET_ID", "").strip()
    secret_key = os.environ.get("KUAIDAILI_SECRET_KEY", "").strip()

    if not secret_id or not secret_key:
        print("✗ 错误：未配置快代理密钥")
        print(f"  请在 {ENV_FILE.name} 文件中添加：")
        print("    KUAIDAILI_SECRET_ID=你的订单SecretId")
        print("    KUAIDAILI_SECRET_KEY=你的订单SecretKey")
        print()
        print("  获取密钥：")
        print("    https://www.kuaidaili.com/uc/api/secret/")
        print("  注意：必须用「订单 API 密钥」，不是「账户 API 密钥」")
        print(f"  SecretId 应为 20 位字符，SecretKey 应为 32 位字符")
        return None, None

    # 校验密钥长度
    if len(secret_id) < 20:
        print(f"⚠️  警告：SecretId 只有 {len(secret_id)} 位字符，正常应为 20 位")
        print("  可能复制不完整，请重新到快代理后台复制完整的 SecretId")

    if len(secret_key) < 32:
        print(f"⚠️  警告：SecretKey 只有 {len(secret_key)} 位字符，正常应为 32 位")
        print("  可能复制不完整，请重新到快代理后台复制完整的 SecretKey")

    return secret_id, secret_key


def sign_hmacsha1(secret_key: str, raw_str: str) -> str:
    """HMAC-SHA1 签名 + Base64 编码"""
    hmac_digest = hmac.new(
        secret_key.encode("utf-8"),
        raw_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(hmac_digest).decode("utf-8")


def build_signed_url(secret_id: str, secret_key: str, num: int) -> str:
    """
    构建 hmacsha1 签名的完整 URL

    签名算法（参考 https://www.kuaidaili.com/doc/api/auth/）：
    1. 所有参数按参数名 ASCII 码升序排序
    2. 拼接请求字符串：param1=value1&param2=value2&...
    3. 拼接签名原文：GET + 请求路径 + ? + 请求字符串
    4. HMAC-SHA1(签名原文, secret_key) → Base64 编码 → URL 编码
    5. 把 signature 加到参数列表里，拼成完整 URL
    """
    # 所有请求参数（不含 signature）
    params = {
        "secret_id": secret_id,
        "sign_type": "hmacsha1",
        "timestamp": str(int(time.time())),
        "num": str(num),
        "format": "text",
        "sep": "2",  # \n 分隔
        # 关键：获取鉴权信息（用户名+密码），否则代理返回 407
        "f_auth": "1",
    }

    # 步骤 1：按参数名 ASCII 码升序排序
    sorted_keys = sorted(params.keys())

    # 步骤 2：拼接请求字符串
    query_str = "&".join(f"{k}={params[k]}" for k in sorted_keys)

    # 步骤 3：拼接签名原文
    raw_str = f"GET{KDL_API_PATH}?{query_str}"

    # 步骤 4：计算签名
    signature = sign_hmacsha1(secret_key, raw_str)
    signature_encoded = urllib.parse.quote(signature, safe="")

    # 步骤 5：拼完整 URL（参数顺序不重要，但保持排序更规范）
    params["signature"] = signature_encoded
    final_query = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    return f"https://{KDL_API_HOST}{KDL_API_PATH}?{final_query}"


def fetch_proxies(url: str) -> list:
    """调用快代理 API 拉取代理列表"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8").strip()
    except urllib.error.URLError as e:
        print(f"✗ 网络请求失败: {e}")
        return []
    except Exception as e:
        print(f"✗ 请求异常: {e}")
        return []

    # 检查错误
    if body.startswith("ERROR"):
        print(f"✗ 快代理返回错误: {body}")
        print()
        # 常见错误码说明
        error_codes = {
            "ERROR(-1)": "无效请求",
            "ERROR(-2)": "订单无效，刚下单请等 1 分钟",
            "ERROR(-3)": "参数错误",
            "ERROR(-4)": "提取失败",
            "ERROR(-104)": "签名错误 - 检查 SecretKey 是否正确",
            "ERROR(-108)": "IP 白名单错误 - 关闭白名单或添加当前 IP",
            "ERROR(-130)": "无效参数 - 检查 SecretId 是否完整（应为 20 位）",
            "ERROR(-132)": "实名核验期间无法调用 - 先完成实名认证",
        }
        for code, desc in error_codes.items():
            if code in body:
                print(f"  原因: {desc}")
                break
        return []

    # 解析代理列表
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    proxies = []
    for line in lines:
        # 格式可能是 "ip:port" 或 "ip:port,附加信息"
        ip_port = line.split(",")[0].strip()
        if ":" in ip_port:
            proxies.append(ip_port)

    return proxies


def save_proxies(proxies: list):
    """覆盖写入 proxies.txt，带鉴权信息的 http 代理格式"""
    # 快代理私密代理同端口同时支持 HTTP 和 SOCKS5
    # 带 f_auth 参数时返回格式为 ip:port:username:password
    # 需要转为 http://username:password@ip:port 格式
    http_proxies = []
    for line in proxies:
        parts = line.strip().split(":")
        if len(parts) >= 4:
            # ip:port:user:pass → http://user:pass@ip:port
            ip, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
            http_proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
        elif len(parts) == 2:
            # 裸 ip:port（无鉴权，可能不可用但保留）
            http_proxies.append(f"http://{parts[0]}:{parts[1]}")

    PROXIES_FILE.write_text("\n".join(http_proxies) + "\n", encoding="utf-8")


def main():
    # 加载 .env
    load_env()

    print(f"[{time.strftime('%H:%M:%S')}] 快代理代理刷新")
    print("-" * 40)

    # 获取密钥
    secret_id, secret_key = get_credentials()
    if not secret_id:
        sys.exit(1)

    # 构建签名 URL
    url = build_signed_url(secret_id, secret_key, FETCH_NUM)
    print(f"拉取 {FETCH_NUM} 个代理...")

    # 拉取代理
    proxies = fetch_proxies(url)
    if not proxies:
        print("✗ 未拉取到代理")
        sys.exit(1)

    # 保存
    save_proxies(proxies)
    print(f"✓ 已写入 {len(proxies)} 个代理到 {PROXIES_FILE.name}")
    print(f"  示例: {proxies[0] if proxies else '无'}")
    print(f"  代理池将在下次刷新时自动筛选")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""代理可用性测试 - 不消耗 IP 额度"""

import urllib.request
import time
from datetime import datetime
from pathlib import Path

PROXIES_FILE = Path(__file__).parent / "proxies.txt"
TARGET = "https://www.bigmodel.cn"

print()
print("=== 代理可用性测试 ===")
print()

if not PROXIES_FILE.exists():
    print("错误: proxies.txt 不存在")
    print("请先运行 manual_refresh_proxy.bat 拉取代理")
    input("按回车退出...")
    raise SystemExit(1)

with open(PROXIES_FILE, encoding="utf-8") as f:
    lines = [l.strip() for l in f if l.strip()]

print(f"proxies.txt 里有 {len(lines)} 个代理")
print(f"测试时间: {datetime.now().strftime('%H:%M:%S')}")
print()
print(f"测试目标: {TARGET} (智谱服务器)")
print()
print("--- 开始测试（最多测前 20 个）---")
print()

ok = 0
fail = 0
timeout_count = 0
auth_fail = 0

for i, line in enumerate(lines[:20]):
    try:
        handler = urllib.request.ProxyHandler({"https": line})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(TARGET, method="HEAD")
        resp = opener.open(req, timeout=4)
        ok += 1
        print(f"  [{i+1:2d}] OK    status={resp.status}")
    except Exception as e:
        fail += 1
        err = str(e)
        if "timed out" in err:
            timeout_count += 1
            short = "TIMEOUT"
        elif "460" in err or "407" in err:
            auth_fail += 1
            short = "AUTH_FAIL"
        else:
            short = err[:40]
        print(f"  [{i+1:2d}] FAIL  {short}")

print()
print("--- 测试结果 ---")
print(f"  成功: {ok} 个")
print(f"  失败: {fail} 个 (超时:{timeout_count}, 认证失败:{auth_fail})")
print()

if ok >= 10:
    print("  [结论] 代理质量良好，可以抢购！")
elif ok > 0:
    print("  [结论] 代理部分可用，建议重新拉取一批")
else:
    print("  [结论] 代理全部失效！")
    print("         原因可能是:")
    print("         - 代理已过期（1-5分钟时效）")
    print("         - 需要重新运行 manual_refresh_proxy.bat")

print()
input("按回车退出...")

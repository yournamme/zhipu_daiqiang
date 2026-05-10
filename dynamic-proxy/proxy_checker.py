#!/usr/bin/env python3
"""
proxy_checker.py — SOCKS5 代理连通性测试工具
════════════════════════════════════════════

对每个代理执行完整的端到端链路测试：
  TCP 握手 → SOCKS5 协商 → CONNECT 目标主机 → TLS 握手
记录从发起连接到完成 TLS 握手的全程耗时，过滤掉超过 --max-latency
阈值或无法连通的代理，输出满足要求的可用列表。

与 dynamic-proxy 的健康检测（Go 实现）口径一致，可在运行前独立
筛选高质量代理，再将输出文件填入 config.yaml，提升整体代理池连通率。

重要：本脚本只生成筛选结果，不会自动影响 GLM Desk 运行时代理。
要让业务请求使用筛选后的代理，必须同时满足：
  1. dynamic-proxy/config.yaml 的 proxy_list_urls 包含输出文件，例如 good_proxies.txt
  2. .env 设置 FALLBACK_PROXY_URL=http://127.0.0.1:17286
  3. dynamic-proxy.exe 正在运行

快速开始
────────
  # 1. 测试本地文件里的代理，最大延迟 3000ms
  python proxy_checker.py --source proxies.txt --max-latency 3000

  # 2. 直接从 URL 拉取代理列表并测试，保存结果
  python proxy_checker.py \\
      --source https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt \\
      --max-latency 4000 --output good.txt

  # 3. 从 dynamic-proxy/config.yaml 自动读取所有代理源
  python proxy_checker.py --from-config config.yaml --max-latency 4000

  # 3.1 生成可供 dynamic-proxy 读取的预筛选代理池文件
  python proxy_checker.py --from-config config.yaml --target www.bigmodel.cn:443 \
      --max-latency 3000 --timeout 6 --concurrency 200 \
      --output good_proxies.txt --show-errors

  # 4. 测试对 google.com 的连通性（境外代理场景）
  python proxy_checker.py --source proxies.txt --target www.google.com:443

  # 5. 宽松模式（跳过 TLS 证书验证，通过率更高）
  python proxy_checker.py --source proxies.txt --no-tls --max-latency 5000

  # 6. 实时查看每个通过的代理 + 失败原因分布
  python proxy_checker.py --source proxies.txt --verbose --show-errors

  python proxy_checker.py --from-config config.yaml --target www.bigmodel.cn:443 --max-latency 3000 --timeout 6 --concurrency 200 --output good_proxies.txt --show-errors

   python proxy_checker.py --source proxies.txt  --target www.bigmodel.cn:443 --max-latency 3000 --timeout 6 --concurrency 200 --output good_proxies.txt --show-errors

python proxy_checker.py --from-config config.yaml --target www.bigmodel.cn:443 --max-latency 3000 --timeout 8 --concurrency 200 --no-tls --output good_proxies.txt --show-errors
python proxy_checker.py --source proxies.txt --target www.bigmodel.cn:443 --max-latency 3000 --timeout 8 --concurrency 200 --no-tls --output goodtest_proxies.txt --show-errors
参数说明
────────
  --source          代理列表来源，支持：
                      - 本地文件路径（每行一个代理地址）
                      - HTTP(S) URL（自动下载内容解析）
                    支持的代理格式（同一文件可混用）：
                      ip:port               → 45.33.32.156:1080
                      socks5://ip:port      → socks5://45.33.32.156:1080
                      socks4://ip:port      → socks4://45.33.32.156:1080
                      http://ip:port        → http://45.33.32.156:8080

  --from-config     自动从 dynamic-proxy 的 config.yaml 中读取
                    proxy_list_urls 列表，逐一拉取后合并测试。
                    等价于手动对每个 URL 分别执行 --source。

  --target          测试目标（格式 host:port，默认 www.bigmodel.cn:443）。
                    建议与实际业务目标保持一致：
                      国内业务 → www.bigmodel.cn:443
                      境外测试 → www.google.com:443

  --max-latency     最大可接受延迟（毫秒，默认 5000）。
                    超过此值的代理标记为「过慢」，不写入 --output。
                    建议根据业务容忍度设置：
                      高实时性（抢购场景）→ 2000~3000ms
                      一般业务            → 4000~5000ms

  --timeout         单个代理的最大等待时间（秒，默认 8）。
                    超时即视为连接失败，不计入「过慢」。
                    建议 timeout >= max-latency/1000 + 1。

  --concurrency     并发测试线程数（默认 100）。
                    线程数越高扫描越快，但会增加本机 CPU 和网络负载。
                    一般设 100~200 即可；超过 300 收益递减。

  --output          通过测试的代理写入此文件（每行一个 ip:port）。
                    写入格式与 dynamic-proxy config.yaml 的
                    proxy_list_urls 兼容，可直接作为本地文件源使用。

  --no-tls          跳过 TLS 证书验证（宽松模式）。
                    对应 dynamic-proxy 的 relaxed 端口（:17284/:17286）。
                    通过率通常比严格模式高 50~100%。

  --verbose         实时输出每个通过测试的代理及其延迟。
                    不影响进度条显示。

  --show-errors     在最终摘要中额外打印失败原因分布（Top 8），
                    便于判断是超时为主还是连接拒绝为主。

输出说明
────────
  ✓ 通过：延迟 ≤ --max-latency，且完成了完整的 TLS 握手
  ~ 过慢：成功连通，但延迟 > --max-latency
  ✗ 失败：连接超时、SOCKS5 协商失败、TLS 错误等

  延迟统计中的「中位」比「平均」更能代表实际使用体验。

注意事项
────────
  - 本脚本仅依赖 Python 标准库，无需 pip install 任何包。
  - 测试结果是当前时刻的快照，免费代理存活周期短（分钟~小时级），
    建议在实际使用前重新检测一次。
  - 若需提高结果稳定性，推荐使用付费国内代理服务商的 API 作为来源。
  - 若要让筛选结果进入运行时代理池，请把 --output 生成的文件写入
    dynamic-proxy/config.yaml 的 proxy_list_urls，例如：- "good_proxies.txt"。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import socket
import ssl
import struct
import sys
import time
import urllib.request
from typing import NamedTuple


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class ProxyResult(NamedTuple):
    proxy: str          # "ip:port"
    ok: bool            # 是否通过（延迟也在阈值内）
    latency_ms: float   # 端到端延迟（ms）；失败时为 0
    error: str          # 失败原因简述；成功时为空


# ---------------------------------------------------------------------------
# SOCKS5 + TLS 探针
# ---------------------------------------------------------------------------

def _socks5_tls_probe(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    timeout: float,
    verify_tls: bool,
) -> float:
    """
    通过 SOCKS5 代理连接 target_host:target_port，完成 TLS 握手。
    返回端到端耗时（ms）。失败时抛出异常。
    """
    start = time.perf_counter()

    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    sock.settimeout(timeout)

    try:
        # ── SOCKS5 问候 ──────────────────────────────────────────────────
        sock.sendall(b"\x05\x01\x00")        # 版本5，1种方法，无需认证
        resp = _recv_exact(sock, 2)
        if resp[0] != 5 or resp[1] != 0:
            raise ConnectionError(f"SOCKS5 认证协商失败: {resp.hex()}")

        # ── SOCKS5 CONNECT ───────────────────────────────────────────────
        host_b = target_host.encode()
        req = (
            struct.pack("!BBBBB", 5, 1, 0, 3, len(host_b))
            + host_b
            + struct.pack("!H", target_port)
        )
        sock.sendall(req)

        # 响应头固定 4 字节，然后根据地址类型读剩余
        head = _recv_exact(sock, 4)
        if head[0] != 5:
            raise ConnectionError(f"SOCKS5 响应版本错误: {head.hex()}")
        if head[1] != 0:
            _SOCKS5_ERRORS = {
                1: "通用失败", 2: "连接不被允许", 3: "网络不可达",
                4: "主机不可达", 5: "连接被拒绝", 6: "TTL 超时",
                7: "命令不支持", 8: "地址类型不支持",
            }
            raise ConnectionError(f"SOCKS5 错误: {_SOCKS5_ERRORS.get(head[1], f'code {head[1]}')}")
        # 跳过绑定地址
        atype = head[3]
        if atype == 1:      # IPv4
            sock.recv(4 + 2)
        elif atype == 4:    # IPv6
            sock.recv(16 + 2)
        elif atype == 3:    # 域名
            dlen = struct.unpack("!B", _recv_exact(sock, 1))[0]
            sock.recv(dlen + 2)

        # ── TLS 握手 ─────────────────────────────────────────────────────
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        tls = ctx.wrap_socket(sock, server_hostname=target_host, do_handshake_on_connect=False)
        try:
            tls.do_handshake()
        finally:
            try:
                tls.close()
            except Exception:
                pass

        return (time.perf_counter() - start) * 1000.0

    finally:
        try:
            sock.close()
        except Exception:
            pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接意外关闭")
        buf += chunk
    return buf


# ---------------------------------------------------------------------------
# 单代理检测
# ---------------------------------------------------------------------------

def check_proxy(
    proxy_addr: str,
    target_host: str,
    target_port: int,
    timeout: float,
    verify_tls: bool,
) -> ProxyResult:
    try:
        # 支持 ip:port / socks5://ip:port / http://ip:port 格式
        addr = proxy_addr.strip()
        for pfx in ("socks5://", "socks4://", "http://", "https://"):
            if addr.startswith(pfx):
                addr = addr[len(pfx):]
                break
        parts = addr.rsplit(":", 1)
        if len(parts) != 2:
            return ProxyResult(proxy_addr, False, 0, "格式不正确，需 ip:port")
        host, port_s = parts[0], parts[1]
        port = int(port_s)

        latency = _socks5_tls_probe(host, port, target_host, target_port, timeout, verify_tls)
        return ProxyResult(proxy_addr, True, latency, "")

    except Exception as exc:
        return ProxyResult(proxy_addr, False, 0, str(exc)[:80])


# ---------------------------------------------------------------------------
# 代理列表获取
# ---------------------------------------------------------------------------

def fetch_proxy_list(source: str) -> list[str]:
    """从 URL 或本地文件读取代理列表（每行一个 ip:port）。"""
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "proxy-checker/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode(errors="replace")
    else:
        with open(source, encoding="utf-8", errors="replace") as f:
            content = f.read()

    proxies: list[str] = []
    seen: set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去协议前缀后判断格式
        addr = line
        for pfx in ("socks5://", "socks4://", "http://", "https://"):
            if addr.startswith(pfx):
                addr = addr[len(pfx):]
                break
        if ":" in addr and addr not in seen:
            seen.add(addr)
            proxies.append(addr)
    return proxies


def fetch_from_config(config_path: str) -> list[str]:
    """从 dynamic-proxy 的 config.yaml 里读取代理源并拉取。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        # 不依赖 pyyaml，手写简单解析
        pass

    # 用简单正则解析 proxy_list_urls
    import re
    with open(config_path, encoding="utf-8") as f:
        content = f.read()

    urls: list[str] = []
    in_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("proxy_list_urls:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("-"):
                url = stripped[1:].strip().strip('"').strip("'")
                if url and not url.startswith("#"):
                    urls.append(url)
            elif stripped and not stripped.startswith("#"):
                # 新的顶层键出现，退出块
                if not stripped.startswith("-"):
                    break

    if not urls:
        raise ValueError(f"在 {config_path} 中未找到 proxy_list_urls")

    proxies: list[str] = []
    seen: set[str] = set()
    for url in urls:
        print(f"  拉取: {url}")
        try:
            batch = fetch_proxy_list(url)
            new = [p for p in batch if p not in seen]
            seen.update(new)
            proxies.extend(new)
            print(f"    → {len(new)} 个代理")
        except Exception as e:
            print(f"    ✗ 拉取失败: {e}", file=sys.stderr)

    return proxies


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SOCKS5 代理连通性测试 — 通过完整 TLS 握手过滤不达标代理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--source", metavar="URL_OR_FILE",
        help=(
            "代理列表来源：本地文件路径 或 HTTP(S) URL。"
            "每行一个地址，支持 ip:port / socks5://ip:port / http://ip:port 格式混用。"
        ),
    )
    src.add_argument(
        "--from-config", metavar="CONFIG_YAML",
        help=(
            "从 dynamic-proxy 的 config.yaml 中读取 proxy_list_urls 列表，"
            "自动拉取并合并所有代理源，等价于对每个 URL 单独执行 --source。"
        ),
    )

    parser.add_argument(
        "--target", default="www.bigmodel.cn:443",
        help=(
            "测试目标（host:port，默认 www.bigmodel.cn:443）。"
            "建议与实际业务目标一致：国内业务用 www.bigmodel.cn:443，境外用 www.google.com:443。"
        ),
    )
    parser.add_argument(
        "--max-latency", type=int, default=5000, metavar="MS",
        help=(
            "最大可接受延迟（毫秒，默认 5000）。"
            "超过此值标记为过慢，不写入 --output。"
            "抢购场景建议 2000~3000，一般业务 4000~5000。"
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=8.0, metavar="S",
        help=(
            "单个代理的最大等待时间（秒，默认 8）。"
            "超时即视为失败，不计入过慢。建议 >= max-latency/1000 + 1。"
        ),
    )
    parser.add_argument(
        "--concurrency", type=int, default=100, metavar="N",
        help=(
            "并发测试线程数（默认 100）。"
            "100~200 适合大多数场景，超过 300 收益递减。"
        ),
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help=(
            "将通过测试的代理（ip:port 格式）写入此文件，按延迟从小到大排序。"
            "可直接作为下次 --source 的输入，或填入 config.yaml 的 proxy_list_urls。"
        ),
    )
    parser.add_argument(
        "--no-tls", action="store_true",
        help=(
            "跳过 TLS 证书验证（宽松模式）。"
            "对应 dynamic-proxy 的 relaxed 端口（:17284/:17286），通过率通常高 50~100%%。"
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="实时输出每个通过测试的代理及其延迟（不影响进度条显示）。",
    )
    parser.add_argument(
        "--show-errors", action="store_true",
        help="在最终摘要中额外打印失败原因分布（Top 8），便于判断超时 vs 拒绝连接的比例。",
    )

    args = parser.parse_args()

    # 解析目标
    tgt_parts = args.target.rsplit(":", 1)
    target_host = tgt_parts[0]
    target_port = int(tgt_parts[1]) if len(tgt_parts) > 1 else 443
    verify_tls = not args.no_tls

    # 拉取代理列表
    print(f"\n{'─'*55}")
    if args.from_config:
        print(f"从配置文件读取代理源: {args.from_config}")
        proxies = fetch_from_config(args.from_config)
    else:
        print(f"代理来源: {args.source}")
        try:
            proxies = fetch_proxy_list(args.source)
        except Exception as exc:
            print(f"✗ 获取失败: {exc}", file=sys.stderr)
            return 1

    if not proxies:
        print("✗ 未找到任何代理", file=sys.stderr)
        return 1

    print(f"共加载 {len(proxies)} 个代理")
    print(f"目标:   {args.target}")
    print(f"过滤:   延迟 ≤ {args.max_latency}ms  |  超时 {args.timeout}s  |  TLS验证 {'开' if verify_tls else '关'}")
    print(f"并发:   {args.concurrency} 线程")
    print(f"{'─'*55}\n")

    # 并发测试
    results: list[ProxyResult] = []
    checked = 0
    total = len(proxies)

    def _print_progress(passed_now: int) -> None:
        pct = checked / total * 100
        w = 35
        filled = int(w * checked / total)
        bar = "█" * filled + "░" * (w - filled)
        print(f"\r[{bar}] {checked}/{total} ({pct:.1f}%) | ✓ {passed_now}", end="", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {
            ex.submit(check_proxy, p, target_host, target_port, args.timeout, verify_tls): p
            for p in proxies
        }
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            results.append(r)
            checked += 1
            passing = sum(1 for x in results if x.ok and x.latency_ms <= args.max_latency)
            _print_progress(passing)
            if args.verbose and r.ok and r.latency_ms <= args.max_latency:
                print(f"\n  ✓ {r.proxy:<25} {r.latency_ms:>5.0f}ms")

    print()  # 进度条换行

    # 统计
    passed = sorted(
        [r for r in results if r.ok and r.latency_ms <= args.max_latency],
        key=lambda r: r.latency_ms,
    )
    slow    = [r for r in results if r.ok and r.latency_ms > args.max_latency]
    failed  = [r for r in results if not r.ok]

    print(f"\n{'═'*55}")
    print(f"测试完成  共 {total} 个代理")
    print(f"  ✓ 通过 (≤{args.max_latency}ms) : {len(passed):>5}")
    print(f"  ~ 过慢 (>{args.max_latency}ms) : {len(slow):>5}")
    print(f"  ✗ 失败              : {len(failed):>5}")
    print(f"{'═'*55}")

    if passed:
        lats = [r.latency_ms for r in passed]
        median = sorted(lats)[len(lats) // 2]
        print(f"\n延迟统计（通过代理）:")
        print(f"  最快: {min(lats):.0f}ms   中位: {median:.0f}ms   最慢: {max(lats):.0f}ms")
        print(f"\n最快的 15 个代理:")
        for r in passed[:15]:
            print(f"  {r.proxy:<26} {r.latency_ms:>5.0f}ms")

    if args.show_errors and failed:
        from collections import Counter
        err_counts = Counter(r.error.split(":")[0].strip() for r in failed)
        print(f"\n失败原因分布（Top 8）:")
        for reason, cnt in err_counts.most_common(8):
            print(f"  {cnt:>5}x  {reason}")

    if args.output:
        if passed:
            with open(args.output, "w", encoding="utf-8") as f:
                for r in passed:
                    f.write(f"{r.proxy}\n")
            print(f"\n已保存 {len(passed)} 个代理 → {args.output}")
        else:
            print("\n没有通过测试的代理，未写入文件。")

    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

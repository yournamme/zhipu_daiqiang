"""Proxy source checker for the built-in proxy pool."""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from dataclasses import replace
from pathlib import Path

from app.proxy_pool.service import (
    RuntimeProxyConfig,
    check_proxy_health,
    fetch_proxy_sources,
    load_proxy_pool_config,
    parse_upstream_proxy,
    read_proxy_source,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check upstream proxies with the same logic used by the built-in proxy pool.",
    )
    parser.add_argument("--from-config", default="proxy_pool.yaml", help="proxy_pool.yaml path")
    parser.add_argument("--source", default="", help="Override with one proxy source file or URL")
    parser.add_argument("--target", default="", help="Health check target, for example www.bigmodel.cn:443")
    parser.add_argument("--max-latency", type=int, default=3000, help="Maximum latency in milliseconds")
    parser.add_argument("--timeout", type=float, default=8, help="Per-proxy timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=200, help="Check concurrency")
    parser.add_argument("--no-tls", action="store_true", help="Skip upstream TLS certificate verification")
    parser.add_argument("--output", default="", help="Write passing proxies to this file")
    parser.add_argument("--show-errors", action="store_true", help="Print failed proxy exceptions")
    args = parser.parse_args()

    config = load_proxy_pool_config(Path(args.from_config))
    if args.source:
        proxies = []
        for line in read_proxy_source(args.source).splitlines():
            proxy = parse_upstream_proxy(line)
            if proxy:
                proxies.append(proxy)
    else:
        proxies = fetch_proxy_sources(config)
    if not proxies:
        print("No proxies found.", file=sys.stderr)
        return 2

    health = config.health_check
    if args.target:
        health = replace(health, target=args.target)
    health = replace(health, total_timeout_seconds=args.timeout)
    config = replace(
        config,
        health_check=health,
        health_check_concurrency=max(1, int(args.concurrency)),
    )
    runtime = RuntimeProxyConfig(max_latency_ms=args.max_latency)
    strict_mode = not args.no_tls

    print(f"Loaded {len(proxies)} proxies; target={config.health_check.target}; strict_tls={strict_mode}")
    passed = []
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.health_check_concurrency) as executor:
        future_map = {
            executor.submit(check_proxy_health, proxy, config, strict_mode=strict_mode): proxy
            for proxy in proxies
        }
        for future in concurrent.futures.as_completed(future_map):
            proxy = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive CLI reporting
                result = None
                if args.show_errors:
                    print(f"FAIL {proxy.address}: {exc}")
            if result and (runtime.max_latency_ms <= 0 or result.latency_seconds * 1000 <= runtime.max_latency_ms):
                passed.append(result)
                print(f"PASS {proxy.raw:<32} {int(result.latency_seconds * 1000):>5}ms")
            else:
                failures += 1

    passed.sort(key=lambda item: (item.latency_seconds, item.proxy.raw))
    print(f"Done. passed={len(passed)} failed={failures}")
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(f"{item.proxy.raw}\n" for item in passed),
            encoding="utf-8",
        )
        print(f"Wrote {len(passed)} proxies to {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

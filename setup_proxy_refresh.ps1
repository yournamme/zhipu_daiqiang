# setup_proxy_refresh.ps1 - 设置定时自动拉取代理（一次性任务）
# 用法：双击 setup_proxy_refresh.bat 运行

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   设置定时自动拉取代理" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "用途：在指定时间自动运行一次代理拉取（只运行一次）"
Write-Host "场景：提前启动服务配置好后，设置 09:57 自动拉取"
Write-Host ""
Write-Host "格式：HH:MM（24小时制），例如 09:57"
Write-Host ""

$runTime = Read-Host "请输入自动拉取时间（如 09:57）"

if (-not $runTime) {
    Write-Host "错误：没有输入时间" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

if ($runTime -notmatch "^\d{1,2}:\d{2}$") {
    Write-Host "错误：时间格式不正确，请用 HH:MM 格式，如 09:57" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

$parts = $runTime.Split(":")
$hour = $parts[0].PadLeft(2, "0")
$minute = $parts[1]
$runTimeFull = "${hour}:${minute}:00"

Write-Host ""
Write-Host "将在 $runTime 自动拉取 50 个代理 IP" -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "确认？(Y/N)"

if ($confirm -ne "Y" -and $confirm -ne "y") {
    Write-Host "已取消" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 0
}

# 删除旧任务
try { schtasks /delete /tn "AegisFlowProxyRefreshOnce" /f 2>$null | Out-Null } catch {}

$today = Get-Date -Format "yyyy/MM/dd"
$pythonExe = "H:\App\daiqiang_zhipu\daiqiang_tool_2\.venv\Scripts\python.exe"
$scriptPath = "H:\App\daiqiang_zhipu\daiqiang_tool_2\refresh_kuaidaili.py"

$result = schtasks /create /tn "AegisFlowProxyRefreshOnce" /tr "$pythonExe $scriptPath" /sc once /st $runTime /sd $today /f 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "   设置成功！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  任务名：AegisFlowProxyRefreshOnce"
    Write-Host "  运行时间：$runTime"
    Write-Host "  消耗：50 个 IP 额度"
    Write-Host ""
    Write-Host "  工作流："
    Write-Host "    1. 现在启动 start.bat + Web 配置好账号/套餐/定时启动"
    Write-Host "    2. $runTime 自动拉取 50 个新鲜代理"
    Write-Host "    3. 代理池会在 1 分钟内自动加载新代理"
    Write-Host "    4. 到定时启动时间自动触发抢购"
    Write-Host ""
    Write-Host "  查看任务状态："
    Write-Host "    schtasks /query /tn AegisFlowProxyRefreshOnce"
    Write-Host ""
    Write-Host "  取消定时拉取："
    Write-Host "    schtasks /delete /tn AegisFlowProxyRefreshOnce /f"
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "设置失败：$result" -ForegroundColor Red
}

Write-Host ""
Read-Host "按回车退出"

# env-check.ps1 - 快速验证 ETH Trader 交易环境 (Windows)

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "     ETH Trader 环境检查" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

$WORKSPACE = "$env:USERPROFILE\.openclaw\workspace"
$ENV_FILE = "$WORKSPACE\.env.trading"

# 1. 检查必要命令
$cmds = @("okx", "curl", "python", "node")
$missing = $false
foreach ($cmd in $cmds) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "✓ $cmd 已安装" -ForegroundColor Green
    } else {
        Write-Host "✗ $cmd 未安装" -ForegroundColor Red
        $missing = $true
    }
}

if ($missing) {
    Write-Host "环境不完整，请先安装缺失的依赖" -ForegroundColor Red
    exit 1
}

# 2. 检查环境变量文件
if (Test-Path $ENV_FILE) {
    Write-Host "✓ 环境文件存在: $ENV_FILE" -ForegroundColor Green
} else {
    Write-Host "✗ 环境文件不存在: $ENV_FILE" -ForegroundColor Red
    exit 1
}

# 3. 加载并检查 API 密钥
$envContent = Get-Content $ENV_FILE -Raw
if ($envContent -match 'OKX_API_KEY\s*=\s*"([^"]+)"' -and
    $envContent -match 'OKX_SECRET_KEY\s*=\s*"([^"]+)"' -and
    $envContent -match 'OKX_PASSPHRASE\s*=\s*"([^"]+)"') {
    Write-Host "✓ API 密钥已配置" -ForegroundColor Green
} else {
    Write-Host "✗ API 密钥未完整配置" -ForegroundColor Red
    exit 1
}

# 4. 自动 patch okx CLI
Write-Host ""
Write-Host "正在检查 OKX CLI ProxyAgent patch..."
$patchOutput = node "$WORKSPACE\scripts\patch-okx-cli.js" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ OKX CLI patch 失败: $patchOutput" -ForegroundColor Red
    exit 1
} else {
    Write-Host "✓ $patchOutput" -ForegroundColor Green
}

# 5. OKX CLI 认证检查
Write-Host ""
Write-Host "正在测试 OKX CLI 认证..."
$ordersOutput = okx swap orders 2>&1
if ($ordersOutput -match "Error: Private endpoint requires API credentials") {
    Write-Host "✗ OKX CLI 认证失败" -ForegroundColor Red
    Write-Host "! 提示: 确保 config.toml 中配置了正确的 API 密钥" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "✓ OKX CLI 认证正常" -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "全部检查通过，环境就绪" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan

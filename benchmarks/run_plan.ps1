# Chạy benchmark SGP theo 3 tầng trên bộ 66 instance của bài nguồn.
#
# Tầng 1: coverage 66/66 (SAT đại diện + CP + ILP nếu license cho phép)
# Tầng 2: ma trận đầy đủ cho 64 instance vừa tài nguyên
# Tầng 3: 2 instance lớn nhất chạy riêng bằng CP
#
# Ví dụ:
#   powershell -ExecutionPolicy Bypass -File benchmarks\run_plan.ps1 -Tier tier1
#   powershell -ExecutionPolicy Bypass -File benchmarks\run_plan.ps1 -Tier tier2 -TimeoutSmall 60
#   powershell -ExecutionPolicy Bypass -File benchmarks\run_plan.ps1 -Tier all -BudgetHours 8

param(
    [ValidateSet("tier1", "tier2", "tier3", "all")]
    [string]$Tier = "tier1",

    [string]$Instances = "benchmarks/benchmark_instances.csv",
    [string]$Output = "benchmarks/results.csv",

    [double]$TimeoutSmall = 120,
    [double]$TimeoutLarge = 300,
    [double]$TimeoutGiant = 3600,
    [double]$BudgetHours = 8,

    [switch]$SkipIlp,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "benchmarks/logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$budget = [string]([int]($BudgetHours * 3600))

function Invoke-Run {
    param([string]$Name, [string[]]$Arguments)

    if ($DryRun) {
        $Arguments = @($Arguments) + @("--dry-run")
        if ($Arguments -notcontains "--limit") { $Arguments += @("--limit", "1") }
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $log = Join-Path $logDir "$stamp-$Name.log"
    Write-Host ""
    Write-Host ("==> {0}" -f $Name) -ForegroundColor Cyan
    Write-Host ("    python -m benchmarks.run_all {0}" -f ($Arguments -join " "))
    & python -m benchmarks.run_all @Arguments 2>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) {
        $script:failed = $true
        Write-Warning ("{0} kết thúc với exit code {1} (xem {2})" -f $Name, $LASTEXITCODE, $log)
    }
}

function Show-Summary {
    if (-not (Test-Path $Output)) { return }
    $rows = Import-Csv $Output
    if (-not $rows) { return }
    Write-Host ""
    Write-Host ("==> Tổng kết {0}: {1} dòng" -f $Output, $rows.Count) -ForegroundColor Cyan
    $rows | Group-Object method, status | Sort-Object Name | ForEach-Object {
        Write-Host ("    {0,-28} {1}" -f $_.Name, $_.Count)
    }
    $bad = $rows | Where-Object {
        $_.expected_status -and $_.status -ne $_.expected_status -and
        $_.status -notin @("TIMEOUT", "UNAVAILABLE", "ERROR")
    }
    if ($bad) {
        Write-Warning ("Có {0} dòng sai so với trạng thái bài nguồn:" -f @($bad).Count)
        $bad | Select-Object instance, method, encoding, solver, sb, status, expected_status |
            Format-Table -AutoSize | Out-String | Write-Host
    }
}

$common = @("--instances", $Instances, "--output", $Output, "--resume")
$script:failed = $false

if ($Tier -in @("tier1", "all")) {
    # 1a. SAT: một cấu hình đại diện, phủ toàn bộ instance
    Invoke-Run "t1-sat" ($common + @(
        "--methods", "sat", "--encodings", "nsc", "--solvers", "cadical",
        "--sb", "none", "--timeout", ([string]$TimeoutSmall),
        "--budget-seconds", $budget))

    # 1b. CP: phủ toàn bộ instance (timeout rộng hơn vì CP chậm ở ca lớn)
    Invoke-Run "t1-cp" ($common + @(
        "--methods", "cp", "--sb", "none", "--timeout", ([string]$TimeoutLarge),
        "--budget-seconds", $budget))

    # 1c. ILP: chỉ chạy được instance nhỏ với license size-limited hiện tại;
    #     các dòng còn lại sẽ là UNAVAILABLE (được ghi lại trung thực)
    if (-not $SkipIlp) {
        Invoke-Run "t1-ilp" ($common + @(
            "--methods", "ilp", "--sb", "none", "--timeout", "60",
            "--budget-seconds", $budget))
    }
}

if ($Tier -in @("tier2", "all")) {
    # 2a. SAT: 4 encoding C2 x 2 solver x 3 cấu hình SB
    Invoke-Run "t2-sat" ($common + @(
        "--methods", "sat",
        "--encodings", "nsc,seqcounter,totalizer,cardnetwrk",
        "--solvers", "cadical,glucose",
        "--sb", "none,sb1,full",
        "--timeout", ([string]$TimeoutSmall),
        "--budget-seconds", $budget))

    # 2b. Order Encoding: 2 solver x SB1 (SB2 chưa hỗ trợ cho Order)
    Invoke-Run "t2-order" ($common + @(
        "--methods", "order", "--solvers", "cadical,glucose",
        "--sb", "none,sb1",
        "--timeout", ([string]$TimeoutSmall),
        "--budget-seconds", $budget))

    # 2c. CP: 3 cấu hình SB
    Invoke-Run "t2-cp" ($common + @(
        "--methods", "cp", "--sb", "none,sb1,full",
        "--timeout", ([string]$TimeoutLarge),
        "--budget-seconds", $budget))
}

if ($Tier -in @("tier3", "all")) {
    # 3. Hai instance lớn nhất: chỉ CP, vì CNF của SAT/Order vượt giới hạn bộ nhớ
    foreach ($label in @("11-11-12", "13-13-14")) {
        Invoke-Run "t3-$label" @(
            "--instances", ("data/giant_{0}.csv" -f $label),
            "--output", $Output, "--resume",
            "--methods", "cp", "--sb", "none",
            "--timeout", ([string]$TimeoutGiant))
    }
}

Show-Summary
Write-Host ""
Write-Host "Log: $logDir" -ForegroundColor DarkGray
if ($script:failed) { exit 1 }

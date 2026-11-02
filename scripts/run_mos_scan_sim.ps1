param([string]$VivadoBin = 'D:\FPGAvivado\Vivado\2022.2\bin')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'rtl'
$runDir = Join-Path $projectRoot 'output\mos_scan_sim'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $runDir
try {
    $xvlog = Join-Path $VivadoBin 'xvlog.bat'
    $xelab = Join-Path $VivadoBin 'xelab.bat'
    $xsim = Join-Path $VivadoBin 'xsim.bat'
    & cmd.exe /d /c call $xvlog --sv `
        (Join-Path $sourceRoot 'ads8688_top.v') `
        (Join-Path $sourceRoot 'mcp4725_i2c.v') `
        (Join-Path $sourceRoot 'mos_scan.v') `
        (Join-Path $projectRoot 'tests\mos_scan_tb.sv')
    if ($LASTEXITCODE -ne 0) { throw 'mos_scan 编译失败' }
    & cmd.exe /d /c call $xelab mos_scan_tb -s mos_scan_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'mos_scan 精化失败' }
    & cmd.exe /d /c call $xsim mos_scan_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'mos_scan 仿真失败' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: mos_scan' -Quiet)) {
        throw 'mos_scan 仿真未通过；检查 xsim.log'
    }
} finally {
    Pop-Location
}

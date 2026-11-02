param([string]$VivadoBin = 'D:\FPGAvivado\Vivado\2022.2\bin')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'rtl'
$runDir = Join-Path $projectRoot 'output\mos_experiment_sim'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $runDir
try {
    $xvlog = Join-Path $VivadoBin 'xvlog.bat'
    $xelab = Join-Path $VivadoBin 'xelab.bat'
    $xsim = Join-Path $VivadoBin 'xsim.bat'
    & cmd.exe /d /c call $xvlog --sv `
        (Join-Path $sourceRoot 'ads8688_top.v') `
        (Join-Path $sourceRoot 'mcp4725_i2c.v') `
        (Join-Path $sourceRoot 'mos_experiment.v') `
        (Join-Path $projectRoot 'tests\mos_experiment_tb.sv')
    if ($LASTEXITCODE -ne 0) { throw 'mos_experiment 编译失败' }
    & cmd.exe /d /c call $xelab mos_experiment_tb -s mos_experiment_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'mos_experiment 精化失败' }
    & cmd.exe /d /c call $xsim mos_experiment_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'mos_experiment 仿真失败' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: mos_experiment' -Quiet)) {
        throw 'mos_experiment 仿真未通过；检查 xsim.log'
    }
} finally {
    Pop-Location
}

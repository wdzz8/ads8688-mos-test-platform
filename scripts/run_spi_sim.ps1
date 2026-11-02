param([string]$VivadoBin = 'D:\FPGAvivado\Vivado\2022.2\bin')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot 'rtl\ads8688_top.v'
$testPath = Join-Path $projectRoot 'tests\ads8688_spi_tb.sv'
$runDir = Join-Path $projectRoot 'output\spi_sim'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $runDir
try {
    $xvlog = Join-Path $VivadoBin 'xvlog.bat'
    $xelab = Join-Path $VivadoBin 'xelab.bat'
    $xsim = Join-Path $VivadoBin 'xsim.bat'
    & cmd.exe /d /c call $xvlog --sv $sourcePath $testPath
    if ($LASTEXITCODE -ne 0) { throw 'Verilog compilation failed' }
    & cmd.exe /d /c call $xelab ads8688_spi_tb -s ads8688_spi_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'Simulation elaboration failed' }
    & cmd.exe /d /c call $xsim ads8688_spi_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'Simulation execution failed' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: all ADS8688 SPI regression checks' -Quiet)) {
        throw 'SPI regression checks did not pass; inspect xsim.log'
    }
} finally {
    Pop-Location
}

param([string]$VivadoBin = 'D:\FPGAvivado\Vivado\2022.2\bin')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'rtl'
$runDir = Join-Path $projectRoot 'output\mcp4725_sim'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Push-Location $runDir
try {
    # Vivado's Windows batch wrappers must be invoked through cmd/call. Direct
    # PowerShell invocation can report exit code 1 even after successful work.
    $xvlog = Join-Path $VivadoBin 'xvlog.bat'
    $xelab = Join-Path $VivadoBin 'xelab.bat'
    $xsim = Join-Path $VivadoBin 'xsim.bat'
    & cmd.exe /d /c call $xvlog --sv (Join-Path $sourceRoot 'mcp4725_i2c.v') (Join-Path $sourceRoot 'mcp4725_wave_test.v') (Join-Path $sourceRoot 'ads8688_top.v') (Join-Path $sourceRoot 'dac_adc_loopback.v') (Join-Path $projectRoot 'tests\mcp4725_i2c_tb.sv')
    if ($LASTEXITCODE -ne 0) { throw 'MCP4725 I2C compilation failed' }
    & cmd.exe /d /c call $xelab mcp4725_i2c_tb -s mcp4725_i2c_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'MCP4725 I2C elaboration failed' }
    & cmd.exe /d /c call $xsim mcp4725_i2c_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'MCP4725 I2C simulation failed' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: MCP4725 I2C write' -Quiet)) {
        throw 'MCP4725 I2C simulation did not pass; inspect xsim.log'
    }
    & cmd.exe /d /c call $xvlog --sv (Join-Path $projectRoot 'tests\mcp4725_wave_tb.sv')
    if ($LASTEXITCODE -ne 0) { throw 'Triangle test compilation failed' }
    & cmd.exe /d /c call $xelab mcp4725_wave_tb -s mcp4725_wave_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'Triangle test elaboration failed' }
    & cmd.exe /d /c call $xsim mcp4725_wave_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'Triangle test execution failed' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: MCP4725 triangle' -Quiet)) {
        throw 'Triangle test did not pass; inspect xsim.log'
    }
    & cmd.exe /d /c call $xvlog --sv (Join-Path $projectRoot 'tests\dac_adc_capture_tb.sv')
    if ($LASTEXITCODE -ne 0) { throw 'Capture test compilation failed' }
    & cmd.exe /d /c call $xelab dac_adc_capture_tb -s dac_adc_capture_tb_sim
    if ($LASTEXITCODE -ne 0) { throw 'Capture test elaboration failed' }
    & cmd.exe /d /c call $xsim dac_adc_capture_tb_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'Capture test execution failed' }
    if (!(Select-String -LiteralPath 'xsim.log' -SimpleMatch 'PASS: ADC/DAC capture' -Quiet)) {
        throw 'Capture test did not pass; inspect xsim.log'
    }
} finally {
    Pop-Location
}

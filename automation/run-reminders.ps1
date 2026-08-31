$ErrorActionPreference = 'Stop'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $automationDir 'automation.py'

try {
    & py -3.14 $pythonScript --reminders
    exit $LASTEXITCODE
} catch {
    $runtimeDir = Join-Path $automationDir 'runtime'
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $message = "$(Get-Date -Format o) | ERRO DO INICIADOR DE LEMBRETES: $($_.Exception.Message)"
    Add-Content -LiteralPath (Join-Path $runtimeDir 'automation.log') -Value $message -Encoding UTF8
    exit 1
}

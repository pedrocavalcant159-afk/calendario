$ErrorActionPreference = 'SilentlyContinue'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$verifyScript = Join-Path $automationDir 'verify.py'
$automationScript = Join-Path $automationDir 'automation.py'
$statusPath = Join-Path $automationDir 'runtime\status.json'
$setupScript = Join-Path $automationDir 'setup.ps1'

& py -3.14 $automationScript --sync-responses | Out-Null
& py -3.14 $verifyScript | Out-Null
$status = $null
if (Test-Path -LiteralPath $statusPath) {
    $status = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notification = New-Object System.Windows.Forms.NotifyIcon
$notification.Visible = $true

if ($status -and $status.ready) {
    $notification.Icon = [System.Drawing.SystemIcons]::Information
    $notification.BalloonTipTitle = 'Automacao UPLI pronta'
    $notification.BalloonTipText = 'Calendario e WhatsApp verificados. Relatorio semanal e lembretes diarios estao prontos.'
    $notification.ShowBalloonTip(7000)
} else {
    $notification.Icon = [System.Drawing.SystemIcons]::Warning
    $notification.BalloonTipTitle = 'Automacao UPLI precisa de atencao'
    $notification.BalloonTipText = 'Abra o assistente para corrigir a configuracao antes do proximo envio.'
    $notification.ShowBalloonTip(9000)

    $shouldOpenSetup = -not $status
    if ($status) {
        $shouldOpenSetup = (-not $status.checks.config) -or ($status.checks.internet -and ((-not $status.checks.calendar) -or (-not $status.checks.whatsapp)))
    }
    if ($shouldOpenSetup) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setupScript)
    }
}

Start-Sleep -Seconds 10
$notification.Dispose()
exit 0

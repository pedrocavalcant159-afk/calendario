$ErrorActionPreference = 'Stop'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $automationDir 'config.json'
$runtimeDir = Join-Path $automationDir 'runtime'
$profileDir = Join-Path $runtimeDir 'browser-profile'
$bridgePath = Join-Path $automationDir 'firebase-bridge.html'
$verifyScript = Join-Path $automationDir 'verify.py'
$chromeCandidates = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
)
$chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chrome) { throw 'Google Chrome nao encontrado.' }

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

Clear-Host
Write-Host 'CONFIGURACAO DA AUTOMACAO UPLI' -ForegroundColor Cyan
Write-Host ''
Write-Host 'O relatorio sera enviado segunda-feira as 9h e os lembretes diariamente as 9h05.'
Write-Host 'Digite exatamente o nome que aparece no WhatsApp.'
Write-Host ''
$currentGroup = [string]$config.group_name
$prompt = if ($currentGroup) { "Nome do grupo [$currentGroup]" } else { 'Nome do grupo' }
$groupName = Read-Host $prompt
if ([string]::IsNullOrWhiteSpace($groupName)) { $groupName = $currentGroup }
if ([string]::IsNullOrWhiteSpace($groupName)) { throw 'O nome do grupo e obrigatorio.' }
$config.group_name = $groupName.Trim()
if ([string]::IsNullOrWhiteSpace([string]$config.first_send_not_before)) {
    $now = Get-Date
    $daysUntilMonday = (([int][DayOfWeek]::Monday - [int]$now.DayOfWeek + 7) % 7)
    $nextRun = $now.Date.AddDays($daysUntilMonday).AddHours(9)
    if ($nextRun -le $now) { $nextRun = $nextRun.AddDays(7) }
    $config | Add-Member -NotePropertyName first_send_not_before -NotePropertyValue $nextRun.ToString('o') -Force
}
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8

$bridgeUri = ([System.Uri]$bridgePath).AbsoluteUri + '?mode=setup'
Write-Host ''
Write-Host 'O Chrome da automacao sera aberto agora.' -ForegroundColor Yellow
Write-Host '1. Entre com a mesma conta usada no calendario.'
Write-Host '2. Abra o WhatsApp Web e conecte o numero pelo QR Code.'
Write-Host '3. Confirme que o grupo aparece na lista.'
Write-Host '4. Feche TODAS as janelas desse Chrome e volte aqui.'
Write-Host ''
Start-Process -FilePath $chrome -ArgumentList @("--user-data-dir=$profileDir", '--no-first-run', $bridgeUri, 'https://web.whatsapp.com/')
Read-Host 'Depois de fechar o Chrome, pressione ENTER para verificar'

& py -3.14 $verifyScript --skip-catchup | Out-Null
$exitCode = $LASTEXITCODE
$statusPage = Join-Path $runtimeDir 'status.html'
if (Test-Path -LiteralPath $statusPage) {
    Start-Process -FilePath $statusPage
}
if ($exitCode -eq 0) {
    Write-Host 'Tudo pronto para o relatorio semanal e os lembretes diarios.' -ForegroundColor Green
} else {
    Write-Host 'Ainda ha itens pendentes. Consulte a pagina de diagnostico aberta.' -ForegroundColor Red
}
Read-Host 'Pressione ENTER para fechar'
exit $exitCode

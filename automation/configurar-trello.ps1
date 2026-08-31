$ErrorActionPreference = 'Stop'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $automationDir 'config.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $config.trello) {
    $config | Add-Member -NotePropertyName trello -NotePropertyValue ([pscustomobject]@{}) -Force
}
if ([string]::IsNullOrWhiteSpace([string]$config.trello.api_key)) {
    $config.trello | Add-Member -NotePropertyName api_key -NotePropertyValue 'd45dbd1071fecc178231b48b73a58e12' -Force
}

Clear-Host
Write-Host 'CONFIGURAR CONCLUSAO NO TRELLO' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Um token pessoal permite ao PC marcar como concluido somente os cartoes vinculados.'
Write-Host 'O token fica somente neste computador, em automation/config.json.'
Write-Host ''
Write-Host 'A pagina do Trello sera aberta para gerar um token com permissao de leitura e escrita.' -ForegroundColor Yellow
Start-Process -FilePath 'https://trello.com/app-key'
Write-Host ''
$token = Read-Host 'Cole o token do Trello e pressione ENTER'
if ([string]::IsNullOrWhiteSpace($token)) { throw 'Nenhum token informado. Nada foi alterado.' }

$config.trello | Add-Member -NotePropertyName token -NotePropertyValue $token.Trim() -Force
$config.trello | Add-Member -NotePropertyName enabled -NotePropertyValue $true -Force
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8
Write-Host ''
Write-Host 'Trello configurado. Os proximos formularios marcados como Concluido atualizarao o cartao vinculado.' -ForegroundColor Green
Read-Host 'Pressione ENTER para fechar'

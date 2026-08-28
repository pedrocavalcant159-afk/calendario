param([string]$CompanyId = '')
$ErrorActionPreference = 'Continue'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $automationDir 'automation.py'
$verifyScript = Join-Path $automationDir 'verify.py'
$statusPage = Join-Path $automationDir 'runtime\status.html'

try { $Host.UI.RawUI.WindowTitle = 'Testes da Automacao UPLI' } catch {}

function Invoke-UpliTest {
    param([string]$Mode, [string]$TestPhone)
    $arguments = @($pythonScript, '--test-mode', $Mode)
    if ($CompanyId) { $arguments += @('--test-company', $CompanyId) }
    if ($TestPhone) { $arguments += @('--test-phone', $TestPhone) }
    $output = & py -3.14 @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    return $exitCode
}

while ($true) {
    Clear-Host
    Write-Host 'TESTES DA AUTOMACAO UPLI' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '1. Diagnostico geral (nao envia mensagem)'
    Write-Host '2. Enviar mensagem simples de teste'
    Write-Host '3. Enviar relatorio semanal de teste'
    Write-Host '4. Enviar lembrete de teste com link'
    Write-Host '0. Fechar'
    Write-Host ''
    $choice = Read-Host 'Escolha uma opcao'

    if ($choice -eq '0') { exit 0 }
    if ($choice -eq '1') {
        & py -3.14 $verifyScript --skip-catchup | Out-Null
        $exitCode = $LASTEXITCODE
        if (Test-Path -LiteralPath $statusPage) { Start-Process -FilePath $statusPage }
        if ($exitCode -eq 0) {
            Write-Host 'Diagnostico concluido. Nenhuma mensagem foi enviada.' -ForegroundColor Green
        } else {
            Write-Host 'O diagnostico encontrou itens que precisam de atencao.' -ForegroundColor Red
        }
        Read-Host 'Pressione ENTER para voltar'
        continue
    }

    $mode = switch ($choice) {
        '2' { 'message' }
        '3' { 'weekly' }
        '4' { 'reminder' }
        default { '' }
    }
    if (-not $mode) { continue }

    Write-Host ''
    $confirmation = Read-Host 'Este teste enviara uma mensagem real no grupo. Digite SIM para continuar'
    if ($confirmation.Trim().ToUpperInvariant() -ne 'SIM') {
        Write-Host 'Teste cancelado.' -ForegroundColor Yellow
        Start-Sleep -Seconds 1
        continue
    }

    $testPhone = Read-Host 'Numero com DDD para receber o teste (ENTER usa o grupo configurado)'
    $exitCode = Invoke-UpliTest -Mode $mode -TestPhone $testPhone.Trim()
    if ($exitCode -eq 0) {
        Write-Host 'Teste concluido com sucesso.' -ForegroundColor Green
    } else {
        Write-Host 'O teste falhou. Consulte o diagnostico ou o registro tecnico.' -ForegroundColor Red
    }
    Read-Host 'Pressione ENTER para voltar'
}

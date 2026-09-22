$ErrorActionPreference = 'Stop'
$automationScript = Join-Path $PSScriptRoot 'automation.py'
try {
    Write-Host 'Abrindo o WhatsApp da automacao. Nenhuma mensagem sera enviada por este comando.' -ForegroundColor Cyan
    & py -3.14 $automationScript --open-whatsapp
    if ($LASTEXITCODE -ne 0) { throw 'O Chrome nao foi aberto corretamente. Consulte o erro mostrado acima.' }
    Write-Host 'WhatsApp visivel para manutencao.' -ForegroundColor Green
    Read-Host 'Quando terminar, pressione ENTER para voltar ao segundo plano' | Out-Null
    & py -3.14 $automationScript --background-whatsapp
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel voltar o WhatsApp ao segundo plano.' }
    Write-Host 'WhatsApp novamente em segundo plano, sem janela aberta.' -ForegroundColor Green
} catch {
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host 'Copie o erro mostrado acima. Pressione ENTER para fechar' | Out-Null
    exit 1
}

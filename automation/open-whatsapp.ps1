$ErrorActionPreference = 'Stop'
$automationScript = Join-Path $PSScriptRoot 'automation.py'
try {
    Write-Host 'Abrindo o WhatsApp da automacao. Nenhuma mensagem sera enviada por este comando.' -ForegroundColor Cyan
    & py -3.14 $automationScript --open-whatsapp
    if ($LASTEXITCODE -ne 0) { throw 'O Chrome nao foi aberto corretamente. Consulte o erro mostrado acima.' }
    Write-Host 'WhatsApp aberto. Deixe essa janela aberta; pode minimizar.' -ForegroundColor Green
} catch {
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host 'Copie o erro mostrado acima. Pressione ENTER para fechar' | Out-Null
    exit 1
}

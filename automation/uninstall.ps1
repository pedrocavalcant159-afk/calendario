$ErrorActionPreference = 'SilentlyContinue'
Unregister-ScheduledTask -TaskName 'Calendario UPLI - Relatorio Semanal' -Confirm:$false
Unregister-ScheduledTask -TaskName 'Calendario UPLI - Lembretes Diarios' -Confirm:$false
Unregister-ScheduledTask -TaskName 'Calendario UPLI - Sincronizar Respostas' -Confirm:$false
Unregister-ScheduledTask -TaskName 'Calendario UPLI - Verificacao ao Entrar' -Confirm:$false
$testShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Testar Automacao UPLI.lnk'
if (Test-Path -LiteralPath $testShortcutPath) {
    Remove-Item -LiteralPath $testShortcutPath -Force
}
Write-Host 'Tarefas da Automacao UPLI removidas. O perfil e os registros locais foram preservados.'

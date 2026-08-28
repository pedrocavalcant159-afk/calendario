param([switch]$SkipSetup)
$ErrorActionPreference = 'Stop'
$automationDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runScript = Join-Path $automationDir 'run.ps1'
$reminderScript = Join-Path $automationDir 'run-reminders.ps1'
$syncScript = Join-Path $automationDir 'run-sync.ps1'
$verifyScript = Join-Path $automationDir 'verify-on-login.ps1'
$runtimeDir = Join-Path $automationDir 'runtime'
$setupScript = Join-Path $automationDir 'setup.ps1'
$testScript = Join-Path $automationDir 'test.ps1'
$taskWeekly = 'Calendario UPLI - Relatorio Semanal'
$taskReminders = 'Calendario UPLI - Lembretes Diarios'
$taskSync = 'Calendario UPLI - Sincronizar Respostas'
$taskLogin = 'Calendario UPLI - Verificacao ao Entrar'
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

$weeklyArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`""
$reminderArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$reminderScript`""
$syncArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`""
$loginArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$verifyScript`""
$weeklyAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $weeklyArguments
$reminderAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $reminderArguments
$syncAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $syncArguments
$loginAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $loginArguments
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '09:00'
$reminderTrigger = New-ScheduledTaskTrigger -Daily -At '09:05'
$syncTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$loginTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskWeekly -Action $weeklyAction -Trigger $weeklyTrigger -Principal $principal -Settings $settings -Description 'Envia no WhatsApp o relatorio semanal do Calendario UPLI.' -Force | Out-Null
Register-ScheduledTask -TaskName $taskReminders -Action $reminderAction -Trigger $reminderTrigger -Principal $principal -Settings $settings -Description 'Envia no WhatsApp lembretes de prazo com links para atualizar os posts.' -Force | Out-Null
Register-ScheduledTask -TaskName $taskSync -Action $syncAction -Trigger $syncTrigger -Principal $principal -Settings $settings -Description 'Aplica no calendario as respostas recebidas pelos formularios.' -Force | Out-Null
Register-ScheduledTask -TaskName $taskLogin -Action $loginAction -Trigger $loginTrigger -Principal $principal -Settings $settings -Description 'Verifica calendario, internet, WhatsApp e recupera envios perdidos.' -Force | Out-Null

$desktop = [Environment]::GetFolderPath('Desktop')
$testShortcutPath = Join-Path $desktop 'Testar Automacao UPLI.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($testShortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $testScript + '"'
$shortcut.WorkingDirectory = $automationDir
$shortcut.Description = 'Abre os testes da Automacao UPLI'
$shortcut.Save()

Write-Host 'Tarefas da Automacao UPLI instaladas.' -ForegroundColor Green
Write-Host 'Relatorio semanal: segunda-feira as 9h.'
Write-Host 'Lembretes de prazo: todos os dias as 9h05.'
Write-Host 'Respostas dos formularios: sincronizadas a cada minuto.'
Write-Host 'Verificacao: sempre que este usuario entrar no Windows.'
Write-Host 'Testes: atalho Testar Automacao UPLI na Area de Trabalho.'

if (-not $SkipSetup) {
    & $setupScript
}

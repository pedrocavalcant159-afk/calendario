param(
    [switch]$ValidateOnly,
    [switch]$Force,
    [switch]$KeepLocalData,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$taskNames = @(
    'Calendario UPLI - Relatorio Semanal',
    'Calendario UPLI - Lembretes Diarios',
    'Calendario UPLI - Sincronizar Respostas',
    'Calendario UPLI - Verificacao ao Entrar'
)
$shortcutNames = @(
    'Abrir WhatsApp da Automacao.lnk',
    'Testar Automacao UPLI.lnk',
    'Reconfigurar Automacao UPLI.lnk',
    'Desinstalar Automacao UPLI.lnk'
)
$localAppDataFull = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
$installRoot = [IO.Path]::GetFullPath((Join-Path $localAppDataFull 'UPLI\CalendarioAutomation'))
$automationDir = Join-Path $installRoot 'automation'

if (-not $installRoot.StartsWith($localAppDataFull, [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($installRoot) -ne 'CalendarioAutomation' -or
    [IO.Path]::GetFileName([IO.Path]::GetDirectoryName($installRoot)) -ne 'UPLI') {
    throw 'O caminho da instalacao nao passou pela validacao de seguranca.'
}

if ($ValidateOnly) {
    Write-Host 'Desinstalador validado.' -ForegroundColor Green
    Write-Host ('Instalacao prevista: ' + $installRoot)
    exit 0
}

Clear-Host
Write-Host 'DESINSTALADOR DA AUTOMACAO UPLI' -ForegroundColor Yellow
Write-Host 'Este processo remove as tarefas, os atalhos, a sessao local do WhatsApp e os registros deste PC.'
Write-Host 'O calendario online, os posts e as mensagens ja enviadas nao serao apagados.'
Write-Host 'Chrome e Python tambem serao preservados, pois podem ser usados por outros programas.'

if (-not $Force) {
    Write-Host ''
    $confirmation = Read-Host 'Digite DESINSTALAR para confirmar'
    if ($confirmation -cne 'DESINSTALAR') {
        Write-Host 'Desinstalacao cancelada. Nada foi removido.' -ForegroundColor Cyan
        if (-not $NonInteractive) { Read-Host 'Pressione ENTER para fechar' | Out-Null }
        exit 0
    }
}

try {
    Write-Host ''
    Write-Host 'Removendo tarefas agendadas...' -ForegroundColor Cyan
    foreach ($taskName in $taskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
    }

    $desktop = [Environment]::GetFolderPath('Desktop')
    foreach ($shortcutName in $shortcutNames) {
        $shortcutPath = Join-Path $desktop $shortcutName
        if (Test-Path -LiteralPath $shortcutPath) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }

    if ($KeepLocalData) {
        Write-Host 'Tarefas e atalhos removidos. A sessao e os registros locais foram preservados.' -ForegroundColor Green
    } elseif (Test-Path -LiteralPath $installRoot) {
        Write-Host 'Fechando somente o Chrome usado pela automacao...' -ForegroundColor Cyan
        $profileDir = Join-Path $automationDir 'runtime\browser-profile'
        try {
            Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction Stop |
                Where-Object {
                    $_.CommandLine -and
                    $_.CommandLine.IndexOf($profileDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
                } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        } catch {
            Write-Host 'Nao foi possivel verificar o Chrome da automacao; continuando a remocao.' -ForegroundColor DarkYellow
        }

        Set-Location ([IO.Path]::GetTempPath())
        Remove-Item -LiteralPath $installRoot -Recurse -Force
        $upliParent = [IO.Path]::GetDirectoryName($installRoot)
        if ((Test-Path -LiteralPath $upliParent) -and
            -not (Get-ChildItem -LiteralPath $upliParent -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $upliParent -Force
        }
        Write-Host 'Automacao UPLI desinstalada deste computador.' -ForegroundColor Green
    } else {
        Write-Host 'As tarefas e os atalhos foram removidos. A pasta da automacao ja nao existia.' -ForegroundColor Green
    }
} catch {
    Write-Host ''
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    if (-not $NonInteractive) { Read-Host 'Pressione ENTER para fechar' | Out-Null }
    exit 1
}

if (-not $NonInteractive) {
    Read-Host 'Pressione ENTER para fechar' | Out-Null
}

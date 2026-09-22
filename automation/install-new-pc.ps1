param(
    [string]$InstallRoot = '',
    [switch]$ValidateOnly,
    [switch]$SkipSetup
)

$ErrorActionPreference = 'Stop'
$sourceAutomation = [IO.Path]::GetFullPath($PSScriptRoot)
$requiredFiles = @(
    'automation.py',
    'config.json',
    'firebase-bridge.html',
    'install.ps1',
    'setup.ps1',
    'open-whatsapp.ps1',
    'test.ps1',
    'uninstall.ps1',
    'verify.py',
    'verify-on-login.ps1'
)

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Find-Chrome {
    $candidates = @(
        'C:\Program Files\Google\Chrome\Application\chrome.exe',
        'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
    )
    return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"
}

function Remove-PreviousScheduledTasks {
    $taskNames = @(
        'Calendario UPLI - Relatorio Semanal',
        'Calendario UPLI - Lembretes Diarios',
        'Calendario UPLI - Sincronizar Respostas',
        'Calendario UPLI - Verificacao ao Entrar'
    )
    foreach ($taskName in $taskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
    }
}

function Remove-PreviousShortcuts {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutNames = @(
        'Abrir WhatsApp da Automacao.lnk',
        'Testar Automacao UPLI.lnk',
        'Reconfigurar Automacao UPLI.lnk',
        'Desinstalar Automacao UPLI.lnk'
    )
    foreach ($shortcutName in $shortcutNames) {
        $shortcutPath = Join-Path $desktop $shortcutName
        if (Test-Path -LiteralPath $shortcutPath) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }
}

function Stop-AutomationChrome([string]$ProfilePath) {
    if ([string]::IsNullOrWhiteSpace($ProfilePath)) { return }
    try {
        Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction Stop |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine.IndexOf($ProfilePath, [StringComparison]::OrdinalIgnoreCase) -ge 0
            } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    } catch {
        Write-Host 'Nao foi possivel confirmar o encerramento do Chrome antigo; continuando a atualizacao.' -ForegroundColor DarkYellow
    }
}

function Merge-PreservedConfig([string]$NewConfigPath, [string]$OldConfigPath) {
    if (-not (Test-Path -LiteralPath $OldConfigPath)) { return }
    $newConfig = Get-Content -LiteralPath $NewConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $oldConfig = Get-Content -LiteralPath $OldConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $oldConfig.PSObject.Properties) {
        $newConfig | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
    }
    $newConfig | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $NewConfigPath -Encoding UTF8
}

$backupRoot = ''
try {
    Clear-Host
    Write-Host 'INSTALADOR DA AUTOMACAO UPLI' -ForegroundColor Green
    Write-Host 'Este assistente prepara este PC como principal ou reserva automaticamente.'

    foreach ($file in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceAutomation $file))) {
            throw "Arquivo obrigatorio ausente no pacote: $file"
        }
    }
    if ($ValidateOnly) {
        Write-Host 'Pacote de instalacao validado.' -ForegroundColor Green
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        $InstallRoot = Join-Path $env:LOCALAPPDATA 'UPLI\CalendarioAutomation'
    }
    $installRootFull = [IO.Path]::GetFullPath($InstallRoot)
    $targetAutomation = Join-Path $installRootFull 'automation'
    $rootPath = [IO.Path]::GetPathRoot($installRootFull)
    if ($installRootFull -eq $rootPath -or [IO.Path]::GetFileName($installRootFull) -eq '') {
        throw 'O caminho da instalacao nao passou pela validacao de seguranca.'
    }
    $targetPrefix = $installRootFull.TrimEnd('\') + '\'
    if (-not $targetAutomation.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A pasta da automacao ficou fora da instalacao informada.'
    }
    $sourcePrefix = $sourceAutomation.TrimEnd('\') + '\'
    if ($sourceAutomation.Equals($installRootFull, [StringComparison]::OrdinalIgnoreCase) -or
        $sourceAutomation.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Extraia o pacote novo em outra pasta antes de atualizar a instalacao existente.'
    }

    $isUpgrade = Test-Path -LiteralPath $targetAutomation
    if ($isUpgrade) {
        Write-Step 'Desinstalando os arquivos e agendamentos da versao anterior'
        $backupRoot = Join-Path ([IO.Path]::GetTempPath()) ('UPLI-Upgrade-' + [Guid]::NewGuid().ToString('N'))
        $backupRootFull = [IO.Path]::GetFullPath($backupRoot)
        $tempRootFull = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $backupRootFull.StartsWith($tempRootFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'A pasta temporaria da atualizacao nao passou pela validacao de seguranca.'
        }
        New-Item -ItemType Directory -Path $backupRootFull -Force | Out-Null
        $oldConfigPath = Join-Path $targetAutomation 'config.json'
        $oldRuntimePath = Join-Path $targetAutomation 'runtime'
        if (Test-Path -LiteralPath $oldConfigPath) {
            Get-Content -LiteralPath $oldConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
        }
        Remove-PreviousScheduledTasks
        Remove-PreviousShortcuts
        Stop-AutomationChrome (Join-Path $oldRuntimePath 'browser-profile')
        if (Test-Path -LiteralPath $oldConfigPath) {
            Copy-Item -LiteralPath $oldConfigPath -Destination (Join-Path $backupRootFull 'config.json') -Force
        }
        if (Test-Path -LiteralPath $oldRuntimePath) {
            Copy-Item -LiteralPath $oldRuntimePath -Destination (Join-Path $backupRootFull 'runtime') -Recurse -Force
        }
        Set-Location $sourceAutomation
        $resolvedInstallRoot = [IO.Path]::GetFullPath($installRootFull)
        if (-not $resolvedInstallRoot.Equals($installRootFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'O destino mudou durante a validacao da atualizacao.'
        }
        Remove-Item -LiteralPath $installRootFull -Recurse -Force
        Write-Host 'Versao anterior removida. Sessao e configuracoes foram preservadas temporariamente.' -ForegroundColor Green
    }

    New-Item -ItemType Directory -Path $targetAutomation -Force | Out-Null

    Write-Step 'Instalando os arquivos da versao nova'
    $sourceFiles = Get-ChildItem -LiteralPath $sourceAutomation -File
    foreach ($sourceFile in $sourceFiles) {
        Copy-Item -LiteralPath $sourceFile.FullName -Destination (Join-Path $targetAutomation $sourceFile.Name) -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $targetAutomation 'runtime') -Force | Out-Null
    if ($isUpgrade) {
        $preservedConfig = Join-Path $backupRootFull 'config.json'
        Merge-PreservedConfig (Join-Path $targetAutomation 'config.json') $preservedConfig
        $preservedRuntime = Join-Path $backupRootFull 'runtime'
        if (Test-Path -LiteralPath $preservedRuntime) {
            Get-ChildItem -LiteralPath $preservedRuntime -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $targetAutomation 'runtime') -Recurse -Force
            }
        }
        $staleLock = Join-Path $targetAutomation 'runtime\automation.lock'
        if (Test-Path -LiteralPath $staleLock) {
            Remove-Item -LiteralPath $staleLock -Force
        }
    }

    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'O Windows Package Manager (winget) nao foi encontrado. Atualize o App Installer pela Microsoft Store.'
    }

    $chrome = Find-Chrome
    if (-not $chrome) {
        Write-Step 'Instalando Google Chrome'
        & winget.exe install --id Google.Chrome --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'A instalacao do Google Chrome falhou.' }
        $chrome = Find-Chrome
        if (-not $chrome) { throw 'O Chrome foi instalado, mas nao foi localizado.' }
    } else {
        Write-Step 'Google Chrome encontrado'
    }

    $pythonReady = $false
    try {
        & py -3.14 -c "import sys; print(sys.executable)" | Out-Null
        $pythonReady = $LASTEXITCODE -eq 0
    } catch {}
    if (-not $pythonReady) {
        Write-Step 'Instalando Python 3.14'
        & winget.exe install --id Python.Python.3.14 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'A instalacao do Python 3.14 falhou.' }
        Refresh-ProcessPath
        & py -3.14 -c "import sys; print(sys.executable)" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'O Python foi instalado, mas o inicializador py nao foi localizado.' }
    } else {
        Write-Step 'Python 3.14 encontrado'
    }

    Write-Step 'Instalando o componente de navegacao em segundo plano'
    & py -3.14 -m pip install --disable-pip-version-check --upgrade playwright
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel instalar o Playwright.' }
    & py -3.14 -c "import playwright; print('Playwright OK')"
    if ($LASTEXITCODE -ne 0) { throw 'O Playwright nao foi validado.' }

    Write-Step 'Registrando as tarefas automaticas deste PC'
    $installScript = Join-Path $targetAutomation 'install.ps1'
    & $installScript -SkipSetup
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel registrar as tarefas automaticas.' }

    $desktop = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    $setupShortcut = $shell.CreateShortcut((Join-Path $desktop 'Reconfigurar Automacao UPLI.lnk'))
    $setupShortcut.TargetPath = 'powershell.exe'
    $setupShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $targetAutomation 'setup.ps1') + '"'
    $setupShortcut.WorkingDirectory = $targetAutomation
    $setupShortcut.Description = 'Conecta novamente o calendario e o WhatsApp da Automacao UPLI'
    $setupShortcut.Save()

    $openShortcut = $shell.CreateShortcut((Join-Path $desktop 'Abrir WhatsApp da Automacao.lnk'))
    $openShortcut.TargetPath = 'powershell.exe'
    $openShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $targetAutomation 'open-whatsapp.ps1') + '"'
    $openShortcut.WorkingDirectory = $targetAutomation
    $openShortcut.Description = 'Abre o WhatsApp da automacao sem enviar mensagens'
    $openShortcut.Save()

    $uninstallShortcutPath = Join-Path $desktop 'Desinstalar Automacao UPLI.lnk'
    $uninstallShortcut = $shell.CreateShortcut($uninstallShortcutPath)
    $uninstallShortcut.TargetPath = 'powershell.exe'
    $uninstallShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $targetAutomation 'uninstall.ps1') + '"'
    $uninstallShortcut.WorkingDirectory = [IO.Path]::GetTempPath()
    $uninstallShortcut.Description = 'Remove as tarefas e os arquivos locais da Automacao UPLI'
    $uninstallShortcut.Save()

    if (-not $SkipSetup) {
        Write-Step 'Conectando calendario e WhatsApp'
        & (Join-Path $targetAutomation 'setup.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'A configuracao das contas ainda possui pendencias.' }
    }

    Write-Step 'Carregando o WhatsApp da automacao em segundo plano'
    & py -3.14 (Join-Path $targetAutomation 'automation.py') --background-whatsapp
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel carregar o WhatsApp em segundo plano. Consulte o erro acima; a atualizacao nao foi validada.' }

    Enable-ScheduledTask -TaskName 'Calendario UPLI - Sincronizar Respostas' | Out-Null
    Start-ScheduledTask -TaskName 'Calendario UPLI - Sincronizar Respostas'
    Write-Step 'Instalacao concluida'
    Write-Host "Arquivos instalados em: $installRootFull" -ForegroundColor Green
    Write-Host 'O WhatsApp da automacao esta carregado em segundo plano, sem janela aberta.' -ForegroundColor Green
    Write-Host 'Este PC assumira como lider somente quando nenhum outro PC ativo estiver liderando.'
    if ($backupRoot) {
        $backupRootFull = [IO.Path]::GetFullPath($backupRoot)
        $tempRootFull = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($backupRootFull.StartsWith($tempRootFull, [StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $backupRootFull)) {
            Remove-Item -LiteralPath $backupRootFull -Recurse -Force
        }
    }
    Read-Host 'Pressione ENTER para fechar'
    exit 0
} catch {
    Write-Host ''
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    if ($backupRoot -and (Test-Path -LiteralPath $backupRoot)) {
        Write-Host ('Copia de seguranca preservada em: ' + $backupRoot) -ForegroundColor Yellow
    }
    Read-Host 'Pressione ENTER para fechar'
    exit 1
}

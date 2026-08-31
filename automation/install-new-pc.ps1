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
    'test.ps1',
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
    New-Item -ItemType Directory -Path $targetAutomation -Force | Out-Null

    Write-Step 'Copiando os arquivos para uma pasta fixa do Windows'
    $sourceFiles = Get-ChildItem -LiteralPath $sourceAutomation -File
    foreach ($sourceFile in $sourceFiles) {
        if ($sourceFile.Name -eq 'config.json' -and (Test-Path -LiteralPath (Join-Path $targetAutomation 'config.json'))) {
            continue
        }
        Copy-Item -LiteralPath $sourceFile.FullName -Destination (Join-Path $targetAutomation $sourceFile.Name) -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $targetAutomation 'runtime') -Force | Out-Null

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

    if (-not $SkipSetup) {
        Write-Step 'Conectando calendario e WhatsApp'
        & (Join-Path $targetAutomation 'setup.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'A configuracao das contas ainda possui pendencias.' }
    }

    Enable-ScheduledTask -TaskName 'Calendario UPLI - Sincronizar Respostas' | Out-Null
    Start-ScheduledTask -TaskName 'Calendario UPLI - Sincronizar Respostas'
    Write-Step 'Instalacao concluida'
    Write-Host "Arquivos instalados em: $installRootFull" -ForegroundColor Green
    Write-Host 'Este PC assumira como lider somente quando nenhum outro PC ativo estiver liderando.'
    Read-Host 'Pressione ENTER para fechar'
    exit 0
} catch {
    Write-Host ''
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host 'Pressione ENTER para fechar'
    exit 1
}

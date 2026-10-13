$ErrorActionPreference = "Stop"
$secure = $null
$bstr = [IntPtr]::Zero
$plain = $null
try {
    $pythonExe = $env:JUBAOPEN_LAUNCH_PYTHON_EXE
    $pythonArgs = $env:JUBAOPEN_LAUNCH_PYTHON_ARGS
    $appDir = $env:JUBAOPEN_LAUNCH_APP_DIR
    $database = $env:JUBAOPEN_LAUNCH_DATABASE
    if ([string]::IsNullOrWhiteSpace($pythonExe)) { throw "Launcher did not provide Python executable." }
    if ([string]::IsNullOrWhiteSpace($appDir)) { throw "Launcher did not provide application directory." }
    if ([string]::IsNullOrWhiteSpace($database)) { throw "Launcher did not provide database path." }
    $firstRun = Join-Path $appDir "setup\first_run.py"
    if (-not (Test-Path -LiteralPath $firstRun -PathType Leaf)) { throw "Initialization script not found: $firstRun" }

    $secure = Read-Host "Initial administrator password (at least 12 characters, letters and digits)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($plain)) { throw "Initial administrator password is required." }
    $env:JUBAOPEN_INITIAL_ADMIN_PASSWORD = $plain

    $arguments = @()
    if (-not [string]::IsNullOrWhiteSpace($pythonArgs)) { $arguments += $pythonArgs }
    $arguments += @("-B", "-u", $firstRun, "--db", $database)
    & $pythonExe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Database initialization process failed with exit code $LASTEXITCODE." }
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Remove-Item Env:JUBAOPEN_INITIAL_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:JUBAOPEN_LAUNCH_PYTHON_EXE -ErrorAction SilentlyContinue
    Remove-Item Env:JUBAOPEN_LAUNCH_PYTHON_ARGS -ErrorAction SilentlyContinue
    Remove-Item Env:JUBAOPEN_LAUNCH_APP_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:JUBAOPEN_LAUNCH_DATABASE -ErrorAction SilentlyContinue
    $plain = $null
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $secure = $null
}

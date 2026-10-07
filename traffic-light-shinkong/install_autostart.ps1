<#
    Starts the ShinKong traffic-light controller by itself every time Windows
    signs in this user.  It registers a Task Scheduler task that runs the
    controller with pythonw.exe (no console window); the controller then
    connects the ETH-to-RS485 and starts the sequence on its own (AUTO_RUN).

    Together with Windows automatic sign-in this gives: power on -> desktop ->
    controller running, with nobody at the PC.

    Run once, signed in as the user the PC signs in automatically, from an
    elevated PowerShell ("Run as administrator") in this folder:

        powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1

    Test without rebooting:   Start-ScheduledTask -TaskName "ShinKong Traffic Light"
    Remove the autostart:     powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1 -Uninstall

    Options:
        -Script   controller file (default: the V21 file next to this script)
        -PythonW  full path of pythonw.exe (default: found through the py launcher or PATH)
#>
param(
    [switch]$Uninstall,
    [string]$Script = (Join-Path $PSScriptRoot "traffic_light_cli_V21_modified_for_ShinKong.py"),
    [string]$PythonW = ""
)

$ErrorActionPreference = "Stop"
$TaskName = "ShinKong Traffic Light"
$User = "$env:USERDOMAIN\$env:USERNAME"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed the scheduled task '$TaskName'."
    return
}

if (-not (Test-Path -LiteralPath $Script)) {
    throw "Controller script not found: $Script"
}
$Script = (Resolve-Path -LiteralPath $Script).Path

if (-not $PythonW) {
    # the py launcher knows the installed Python even when it is not on PATH
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $python = & $py.Source -3 -c "import sys; print(sys.executable)"
        if ($python) { $PythonW = Join-Path (Split-Path $python) "pythonw.exe" }
    } else {
        $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($found) { $PythonW = $found.Source }
    }
}
if (-not $PythonW -or -not (Test-Path -LiteralPath $PythonW)) {
    throw "pythonw.exe not found; pass it with -PythonW 'C:\path\to\pythonw.exe'"
}

$action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Script`"" `
    -WorkingDirectory (Split-Path $Script)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
# no 3-day time limit, ignore battery state, never a second copy,
# retry a failed start every minute
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force `
        -Description "ShinKong traffic-light controller, starts at sign-in of $User" | Out-Null
} catch {
    throw ("Could not register the task ($($_.Exception.Message)). " +
           "Open PowerShell with 'Run as administrator' and run this script again.")
}

Write-Host "Registered '$TaskName':"
Write-Host "    when    : $User signs in"
Write-Host "    runs    : $PythonW `"$Script`""
Write-Host "Test now  : Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "Remaining : turn on automatic sign-in for $User (see the instructions)."

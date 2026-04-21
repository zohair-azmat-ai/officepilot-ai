# OfficePilot AI — Task Scheduler installer
# RIGHT-CLICK this file -> "Run with PowerShell" (as Administrator)
# Run once; re-run any time to reset the task.

$taskName = "OfficePilotAI_Backend"
$vbsPath  = "C:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent\start_backend.vbs"
$userId   = "$env:USERDOMAIN\$env:USERNAME"

# Remove any existing task with the same name
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Build the task XML directly — avoids all New-ScheduledTaskSettingsSet
# parameter compatibility issues across Windows 10 PowerShell versions.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$userId</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$userId</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$vbsPath"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null

if ($?) {
    Write-Host ""
    Write-Host "[OK] Task '$taskName' installed." -ForegroundColor Green
    Write-Host "     Trigger : logon + 30-second delay"
    Write-Host "     Action  : wscript.exe `"$vbsPath`""
    Write-Host "     Log     : C:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent\startup.log"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[FAIL] Task registration failed. Are you running as Administrator?" -ForegroundColor Red
    Write-Host ""
}

Read-Host "Press Enter to close"

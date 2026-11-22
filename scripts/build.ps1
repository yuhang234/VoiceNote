<#
VoiceNote 一键构建。

产物（都在 dist\ 下）：
    VoiceNote\                      便携版目录，直接双击里面的 VoiceNote.exe
    VoiceNote-Portable-<版本>.zip   便携版压缩包
    VoiceNote-Setup-<版本>.exe      Windows 安装器（需要 Inno Setup）

用法（在项目根目录）：
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1

没装 Inno Setup 也能跑 —— 脚本检测不到 ISCC 会跳过安装器并明确提示，
便携版照样出得来。想打安装器：winget install JRSoftware.InnoSetup

注意：这里刻意用 $ErrorActionPreference = "Continue"。
Windows PowerShell 5.1 有个坑：EAP 设为 Stop 时，任何原生命令往 stderr 写东西
都会被当成终止性错误 —— 而 PyInstaller 的进度信息正是写到 stderr 的，
一开跑就会中断。所以改为逐条检查 $LASTEXITCODE。
#>

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$dist = Join-Path $root "dist"
$py = Join-Path $root ".venv\Scripts\python.exe"
$pyi = Join-Path $root ".venv\Scripts\pyinstaller.exe"

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "    $text" -ForegroundColor DarkGray }
function Fail($text) { Write-Host $text -ForegroundColor Red; exit 1 }
function HumanSize($bytes) { "{0:N1} MB" -f ($bytes / 1MB) }

if (-not (Test-Path $py)) { Fail "找不到 $py —— 先跑 scripts\setup.ps1" }

$version = (& $py -c "from voicenote import __version__; print(__version__)" 2>&1 | Select-Object -First 1).Trim()
Write-Host "VoiceNote $version" -ForegroundColor Green

Step "检查 PyInstaller"
if (-not (Test-Path $pyi)) {
    Note "未安装，正在安装…"
    uv pip install pyinstaller
    if (-not (Test-Path $pyi)) { Fail "PyInstaller 安装失败" }
}

Step "生成图标"
& $py "packaging\make_icon.py"
if ($LASTEXITCODE -ne 0) { Fail "图标生成失败" }

Step "打包（要复制约 2.3GB，慢是正常的）"
$sw = [Diagnostics.Stopwatch]::StartNew()
& $pyi --noconfirm --clean "packaging\voicenote.spec"
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller 失败" }
$sw.Stop()
Note "耗时 $([int]$sw.Elapsed.TotalSeconds)s"

$exe = Join-Path $dist "VoiceNote\VoiceNote.exe"
if (-not (Test-Path $exe)) { Fail "没找到 $exe" }

# 打包最容易出的问题是"进程能起来但 GPU 没生效"—— 那种情况慢十倍却看不出错。
# 所以构建时强制跑一次自检，跑不过就直接失败，不产出坏包。
Step "验证打包产物（跑端到端自检）"
$proc = Start-Process -FilePath $exe -ArgumentList "--selftest" -Wait -PassThru -NoNewWindow
$log = Join-Path $env:USERPROFILE "VoiceNote\logs\voicenote.log"
if (Test-Path $log) {
    Get-Content $log -Tail 20 |
        Where-Object { $_ -match "通过|失败|警告|RTF" } |
        Select-Object -Last 4 |
        ForEach-Object { Note $_ }
}
if ($proc.ExitCode -ne 0) {
    Write-Host "自检未通过（退出码 $($proc.ExitCode)）—— 打包产物有问题，不继续" -ForegroundColor Red
    Write-Host "完整日志：$log" -ForegroundColor Red
    exit 1
}
Note "自检通过"

# 打包后核对：过滤后的 nvidia DLL 必须真的进了产物。
# 以前是整目录复制，漏包也看不出；现在显式挑文件，所以这里多一道门禁。
Step "核对 CUDA DLL 是否进入产物"
$requiredDlls = @("nvidia\cudnn\bin\cudnn64_9.dll", "nvidia\cublas\bin\cublas64_12.dll")
$internal = Join-Path $dist "VoiceNote\_internal"
foreach ($rel in $requiredDlls) {
    $full = Join-Path $internal ($rel -replace '\\', '/')
    if (-not (Test-Path $full)) {
        Write-Host "    缺 $rel —— GPU 会静默回落 CPU，不出包" -ForegroundColor Red
        exit 1
    }
    Write-Host ("    ok  $rel  ({0:N1} MB)" -f ((Get-Item $full).Length / 1MB)) -ForegroundColor DarkGray
}

# 体积去向一目了然：打包体积异常时，第一眼看这行就知道是谁在膨胀。
$internalTops = Get-ChildItem $internal -Directory -ErrorAction SilentlyContinue |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            MB   = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
        }
    } |
    Sort-Object MB -Descending
$internalTops | ForEach-Object { Write-Host ("    {0,-28} {1,10:N1} MB" -f $_.Name, $_.MB) -ForegroundColor DarkGray }
Write-Host ("    {0,-28} {1,10:N1} MB" -f "(dist/VoiceNote 合计)",
    ((Get-ChildItem (Join-Path $dist 'VoiceNote') -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))

Step "打便携版 ZIP"
$zip = Join-Path $dist "VoiceNote-Portable-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
# 用 .NET 的 ZipFile 而不是 Compress-Archive：后者在 2GB 以上不可靠
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    (Join-Path $dist "VoiceNote"),
    $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)
if (Test-Path $zip) { Note "$zip  ($(HumanSize (Get-Item $zip).Length))" }

Step "打包安装器"
$iscc = $null
foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )) {
    if (Test-Path $candidate) { $iscc = $candidate; break }
}

$setup = Join-Path $dist "VoiceNote-Setup-$version.exe"
if ($iscc) {
    & $iscc "/DAppVersion=$version" "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup 编译失败" }
    if (Test-Path $setup) { Note "$setup  ($(HumanSize (Get-Item $setup).Length))" }
}
else {
    Write-Host "    未找到 Inno Setup，跳过安装器（便携版不受影响）" -ForegroundColor Yellow
    Write-Host "    想打安装器就执行：winget install JRSoftware.InnoSetup" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "构建完成。产物：" -ForegroundColor Green
Get-ChildItem $dist -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "VoiceNote-*" } |
    ForEach-Object {
        if ($_.PSIsContainer) {
            $size = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
            Write-Host ("  {0,-34} {1}" -f "$($_.Name)\", (HumanSize $size))
        }
        else {
            Write-Host ("  {0,-34} {1}" -f $_.Name, (HumanSize $_.Length))
        }
    }

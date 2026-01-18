# 豆包视频生成插件FFmpeg下载脚本
# 该脚本用于自动下载FFmpeg并解压到指定目录

# 设置下载URL和目标目录
$pluginDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetDir = Join-Path $pluginDir "ffmpeg"

# 创建目标目录
if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir | Out-Null
    Write-Host "已创建目录: $targetDir"
}

# 根据系统架构选择合适的FFmpeg版本
$is64Bit = [Environment]::Is64BitOperatingSystem
$ffmpegUrl = if ($is64Bit) {
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
} else {
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win32-gpl.zip"
}

# 下载FFmpeg
$tempZip = Join-Path $env:TEMP "ffmpeg.zip"
Write-Host "正在下载FFmpeg..."
Write-Host "下载地址: $ffmpegUrl"

# 使用Invoke-WebRequest下载
try {
    Invoke-WebRequest -Uri $ffmpegUrl -OutFile $tempZip -UseBasicParsing
    Write-Host "FFmpeg下载完成，保存到: $tempZip"
} catch {
    Write-Host "下载失败: $_" -ForegroundColor Red
    exit 1
}

# 解压FFmpeg
Write-Host "正在解压FFmpeg..."

# 创建临时解压目录
$tempExtract = Join-Path $env:TEMP "ffmpeg_extract"
if (Test-Path $tempExtract) {
    Remove-Item -Recurse -Force $tempExtract | Out-Null
}
New-Item -ItemType Directory -Path $tempExtract | Out-Null

# 解压
try {
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
    Write-Host "FFmpeg解压完成"
} catch {
    Write-Host "解压失败: $_" -ForegroundColor Red
    exit 1
}

# 查找ffmpeg.exe所在目录
$ffmpegExe = Get-ChildItem -Path $tempExtract -Recurse -Name "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    Write-Host "未找到ffmpeg.exe，请手动下载并配置" -ForegroundColor Red
    exit 1
}

# 获取ffmpeg.exe的完整路径
$ffmpegExePath = Join-Path $tempExtract $ffmpegExe
$ffmpegParentDir = Split-Path -Parent $ffmpegExePath

# 复制所有必要文件到目标目录
Write-Host "正在复制FFmpeg文件到目标目录..."
Copy-Item -Path "$ffmpegParentDir\*" -Destination $targetDir -Recurse -Force

# 验证安装
$finalFfmpegPath = Join-Path $targetDir "ffmpeg.exe"
if (Test-Path $finalFfmpegPath) {
    Write-Host "FFmpeg安装成功！"
    Write-Host "FFmpeg路径: $finalFfmpegPath"
    Write-Host ""
    Write-Host "===== 安装信息 ====="
    & $finalFfmpegPath -version | Select-Object -First 5
} else {
    Write-Host "FFmpeg安装失败，未找到可执行文件" -ForegroundColor Red
    exit 1
}

# 清理临时文件
Write-Host ""
Write-Host "正在清理临时文件..."
Remove-Item -Path $tempZip -Force | Out-Null
Remove-Item -Path $tempExtract -Recurse -Force | Out-Null
Write-Host "临时文件清理完成"

Write-Host ""
Write-Host "===== 配置完成 ====="
Write-Host "FFmpeg已成功安装到: $targetDir"
Write-Host "豆包视频生成插件现在可以使用FFmpeg功能了"
Write-Host "请确保在config.toml中正确配置了其他参数"
Write-Host ""
Write-Host "使用说明:"
Write-Host "1. 确保Napcat已正确配置并运行"
Write-Host "2. 生成视频: /video 提示文本"
Write-Host "3. 查看视频列表: /豆包视频列表"
Write-Host "4. 播放视频: /播放豆包 视频名"

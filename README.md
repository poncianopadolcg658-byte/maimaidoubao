# 豆包视频生成插件使用教程

## 功能说明

本插件基于豆包API实现视频生成功能，并支持多种视频参数配置和多种发送方式。主要功能包括：

- `/video 提示文本` - 生成视频
- `/video 模型ID 提示文本` - 指定模型生成视频
- `/豆包模型列表` - 查看支持的模型列表
- `/选择模型 模型编号` - 选择默认模型（自动更新配置）
- `/豆包视频列表` - 查看所有生成的视频
- `/播放豆包 视频标识符` - 发送指定视频（支持编号或名称模糊匹配）

## 环境配置

### 1. Napcat配置

Napcat是一个用于发送视频的工具，需要按照以下步骤配置：

#### 安装Napcat

1. 从Napcat官方网站下载最新版本：https://napcat.dev/
2. 按照官方教程完成安装和登录

#### 启用HTTP API

1. 打开Napcat的设置界面
2. 找到"HTTP API"选项
3. 启用HTTP API服务
4. 设置API端口（默认8090，可自定义）
5. 设置API Token（可选，建议设置）
6. 保存设置

#### 配置插件

在插件的`config.toml`文件中配置Napcat相关参数：

```toml
[napcat]
port = 8090  # 与Napcat设置中的端口一致
token = "your_napcat_token"  # 如果设置了Token，这里需要填写
```

### 2. FFmpeg配置（可选）

FFmpeg是一个用于处理音视频的工具，本插件在某些高级功能中可能需要它，但基本功能不需要。

如果您需要使用高级功能，可以按照以下步骤配置FFmpeg：

#### 下载FFmpeg

1. 访问FFmpeg官网：https://ffmpeg.org/
2. 下载适合您操作系统的版本
3. 解压并将可执行文件添加到系统PATH中，或者放在插件目录下的`ffmpeg`文件夹

#### 配置FFmpeg路径

如果您选择将FFmpeg放在插件目录下，请确保可执行文件位于以下路径：
```
plugins/doubao_video_generator/ffmpeg/ffmpeg.exe  # Windows
plugins/doubao_video_generator/ffmpeg/ffmpeg      # Linux/macOS
```

## 插件配置

### 获取API密钥

1. 访问火山方舟控制台：https://console.volcengine.com/ark/
2. 注册并登录账号
3. 创建API密钥
4. 复制API密钥备用

### config.toml 示例

```toml
[api]
api_key = "your_api_key"  # 从火山方舟控制台获取的API密钥
api_base = "https://ark.cn-beijing.volces.com/api/v3"  # API基础地址
model_id = "doubao-seedance-1-5-pro-251215"  # 默认模型ID

[video]
ratio = "16:9"  # 视频宽高比，可选值：16:9, 4:3, 1:1, 9:16, 3:4, adaptive
duration = 5    # 视频时长（秒）
watermark = false  # 是否添加水印
return_last_frame = false  # 是否返回视频尾帧图像
generate_audio = true  # 是否生成音频
draft = false  # 是否生成样片（快速预览）

[settings]
max_wait_time = 600  # 最大等待时间（秒）
poll_interval = 30  # 状态查询间隔（秒）
auto_download = true  # 是否自动下载视频到本地
download_dir = ""  # 视频下载目录，留空则使用插件目录下的videos文件夹
keep_video_files = true  # 是否保留下载的视频文件

[napcat]
port = 8090  # Napcat API端口
token = ""  # Napcat API Token
```

## 使用方法

### 生成视频

使用`/video`命令生成视频，支持指定模型：

```
# 使用默认模型
/video 一只可爱的小猫在玩球

# 指定模型
/video doubao-seedance-1-5-pro-251215 一只可爱的小猫在玩球
```

### 模型管理

```
# 查看支持的模型列表
/豆包模型列表

# 选择默认模型
/选择模型 1
```

支持的模型列表：
- doubao-seedance-1-0-pro-250528 (基础视频生成模型)
- doubao-seedance-1-5-pro-251215 (高级视频生成模型，支持音频生成和图像输入)
- doubao-seedance-1-0-lite-i2v-250428 (轻量级图生视频模型)

### 视频列表

```
# 查看所有生成的视频
/豆包视频列表
```

返回格式：
```
📋 豆包视频列表
列表: 1.mp4，一只猫在草地里玩耍，2.mp4，晴朗的蓝天之下，一大片白色的雏菊花田
```

### 播放视频

```
# 根据编号播放视频
/播放豆包 1

# 根据名称模糊匹配播放视频
/播放豆包 小猫
```

## 视频存储

所有生成的视频自动下载到以下目录：
```
plugins/doubao_video_generator/videos/
```

视频文件命名格式：
```
{编号}.mp4
```

视频元数据存储在：
```
plugins/doubao_video_generator/videos/metadata.json
```

元数据包含以下信息：
- 视频编号
- 生成提示词
- 模型ID
- 原始文件名
- 创建时间

您可以通过`/豆包视频列表`命令查看所有视频的详细信息。

## 故障排除

### 视频发送失败

1. 检查Napcat是否正常运行
2. 检查API端口和Token是否配置正确
3. 检查视频文件是否存在
4. 查看插件日志获取详细错误信息

### 视频生成失败

1. 检查API密钥是否有效
2. 检查网络连接
3. 查看插件日志获取详细错误信息

## 日志查看

插件日志位于：
```
logs/plugin.doubao_video_generator.log
```

## 版本信息

- 插件版本：2.0.0
- 支持的豆包模型：
  - doubao-seedance-1-0-pro-250528 (基础视频生成模型)
  - doubao-seedance-1-5-pro-251215 (高级视频生成模型，支持音频生成和图像输入)
  - doubao-seedance-1-0-lite-i2v-250428 (轻量级图生视频模型)
- 插件作者：MaiBot
- 插件描述：使用豆包API生成视频，支持多种视频参数配置和多种发送方式

## 注意事项

1. 视频生成可能需要较长时间，请耐心等待
2. 生成的视频文件可能较大，请确保有足够的存储空间
3. 使用Napcat发送大文件时可能会出现超时，建议适当调整超时设置
4. 请遵守相关法律法规，不要生成或传播违法内容

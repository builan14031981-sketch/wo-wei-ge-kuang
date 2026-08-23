# 我为歌狂 An1.0

聚合全网音源的 Windows 音乐下载器，一键将歌曲下载为 **MP3 320Kbps (CBR)** 并写入 ID3v2 元数据标签。

## ✨ 功能特性

- **多源聚合搜索**：网易云音乐 / QQ音乐 / 酷狗音乐 / 酷我音乐 / Bilibili 音频
- **歌单批量解析**：支持酷狗、网易云**公开**歌单链接（粘贴分享链接即可解析整张歌单）
- **批量并发下载**：多线程并行（默认 12 线程，可在设置中调整 4~16）
- **可中断 / 停止**：下载中可随时「停止下载」，进行中的任务会被真实中断（不再卡死）
- **码率可选**：320Kbps 高保真 / 192Kbps 标准（设置中切换）
- **下载管理**：进度可视化、打开文件位置、试听、删除本地文件
- **macOS 风格 UI**：浅色极简界面（PyQt6 + QSS）

## 📦 下载与安装

### 方式一：便携版（推荐）
解压 `我为歌狂便携版.zip`，双击 `WoWeiGeKuang.exe` 即可运行，**无需安装、免 ffmpeg**（ffmpeg 已内嵌）。

### 方式二：安装版
运行 `我为歌狂安装版.exe`，按向导安装，开始菜单/桌面生成快捷方式。
> 安装版由仓库内 `build/installer.nsi` 经 NSIS 编译生成。

## 🚀 使用说明

1. **单曲搜索**：输入「歌名 歌手」→ 搜索 → 勾选 → 批量下载 / 单首下载。
2. **歌单解析**：粘贴酷狗或网易云**公开**歌单链接 → 解析 → 一键下载。
3. **下载管理**：在「下载管理」页查看进度、停止、打开目录、试听、删除。
4. **设置**：修改输出目录、码率、并发线程数（即时生效）。

## ⚠️ 已知限制

- **网易云「我的」/私有歌单需要登录**，当前版本无登录功能，无法解析。请将歌单设为**公开**后使用。
- 音频来源依赖第三方聚合接口 `music-api.gdstudio.xyz`，接口不可用时会搜索失败（已做容错）。

## 🛠️ 从源码构建

```bash
pip install PyQt6 qtawesome requests pyinstaller imageio-ffmpeg
# 取 ffmpeg 放到项目根目录（打包用）
python -c "import imageio_ffmpeg,shutil; shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(),'ffmpeg.exe')"

# 便携版（生成 dist/WoWeiGeKuang/）
pyinstaller -y --noconfirm --windowed --name WoWeiGeKuang ^
  --icon app_icon.ico --add-binary "ffmpeg.exe;." --collect-data qtawesome ^
  --hidden-import qtawesome main.py

# 安装版（需 NSIS）
makensis build/installer.nsi
```

## 📁 项目结构

```
main.py          # 主界面 / 线程 / 下载管理
core_engine.py   # 搜索 / 歌单解析 / 下载转码引擎
styles.py        # macOS 风格 QSS 样式
build/installer.nsi  # NSIS 安装脚本
```

## 📜 免责声明

本工具仅用于个人学习与技术研究，请遵守相关平台服务条款与当地法律法规，下载内容版权归原作者所有。

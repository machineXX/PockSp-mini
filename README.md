# PockSp 用户上位机与 V33 外壳

本项目提供 PockSp 光尺的 Windows USB 用户上位机，以及前置传感器 V33 外壳的打印文件。

## Windows 用户上位机

- [下载 Windows x64 EXE](./PockSp-Viewer-Windows-x64.exe)，双击运行，通过 USB 连接支持用户版 USB 协议 v1 的光尺。
- [主程序](./打开上位机.pyw) · [界面模块](./user_viewer_theme.py) · [MIT 许可证](./LICENSE) · [运行与构建](#source-and-build)
- [第三方许可证](./THIRD-PARTY-NOTICES.txt) · [SHA-256 校验值](./SHA256SUMS.txt)

上位机显示仪器的光谱、测光与频闪读数，可操作仪器界面。测量结果和绘图坐标通过 USB 在本地传输，传感器校准和光谱重建在固件内完成。

## V33 前置传感器外壳

- [前壳 STL](./V33_front_shell.stl) · [后壳 STL](./V33_rear_shell.stl) · [V27 按键帽 STL](./V27_push_button.stl) · [打印说明](./打印说明_V33.txt)

前后壳各打印一件。模型单位为毫米，按 100% 导入。继续使用 V27 按钮帽。切片使用 0.4 mm 喷嘴、0.1 mm 层高和自动支撑验证，实物安装待首件试配。

作者：褪色者 kud。小红书号 `5421294625`，二维码可从上位机的「作者信息」打开。

## 社区外壳

- 林凯手绘蛋糕：[光谱仪外套壳（普通款、相机冷靴款、挂绳款，含打印说明）](./enclosures/林凯手绘蛋糕/)。
- 大雨：[测光表外壳（底壳与上盖，STEP 格式）](./enclosures/大雨/)。

<a id="source-and-build"></a>

## 源码与构建

Windows x64 用户可以直接打开 `PockSp-Viewer-Windows-x64.exe`。从源码运行请安装带 Tk 的 Python 3.9 或更高版本，然后在项目目录运行：

```bat
python -m pip install -r requirements.txt
python 打开上位机.pyw
```

## 构建 Windows x64 EXE

在 Windows 上使用带 Tk 的 64 位 Python 3.13，在项目目录运行：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --noupx --name PockSp-Viewer-Windows-x64 --add-data "author-card.png:." 打开上位机.pyw
```

构建完成后可在 `dist` 中找到 EXE。

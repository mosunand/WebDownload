# WebDownload — 资源爬虫

![Logo](icon/logo.ico)

一个基于 **PySide6 + Playwright + httpx** 的桌面端网页资源抓取工具。  
无边框 iOS 风毛玻璃 UI,真浏览器渲染扫描,支持 JS 动态加载、懒加载图片、登录态保留,并发流式下载。

> 适合需要批量下载网页图片 / 音频 / 视频 / CSS / JS / 完整 HTML 的场景。

---

## ✨ 功能特性

### 扫描能力
- **真浏览器渲染** — 内置 Chromium,JS 动态加载、SPA 单页应用也能扫到
- **懒加载触发** — 渐进自动滚动,触发 `data-src` / `srcset` / 无限滚动等懒加载资源
- **计算样式背景图** — 不只扫 `<img>`,还能提取 CSS `background-image` 里的图片
- **网络响应拦截** — 监听所有网络请求,补抓 DOM 里没有的 XHR / 动态媒体资源
- **登录态保留** — 内置持久化用户数据目录,可先登录再扫描,支持需登录的页面
- **分类整理** — 自动按 图片 / 音频 / 视频 / CSS / JS / HTML 分类

### 下载能力
- **httpx 并发下载** — 共享连接池,多线程流式下载,可配置并发数(1–32)
- **实时进度** — 单文件字节级进度 + 整体进度条,进度回调节流避免卡 UI
- **可取消** — 随时取消,自动清理未完成的半截文件
- **智能命名** — 自动去重、冲突加序号,按类型分子目录保存
- **会话目录** — 每次下载按 `时间+域名` 建独立目录,不混在一起

### 界面
- **iOS 风毛玻璃** — Windows DWM Acrylic / BlurBehind 真实模糊背景
- **无边框自定义标题栏** — 系统原生拖动,支持最大化 / 最小化 / 关闭 / 贴边吸附
- **全自绘控件** — 玻璃卡片、药丸按钮(按压回弹动画)、iOS 滑动开关
- **设置持久化** — 保存目录、并发数、自定义图标,JSON 配置文件
- **高 DPI 适配** — PassThrough 缩放策略,4K 屏不糊

---

## 📸 截图

> *(放一张运行截图到这里,建议放在 `docs/screenshot.png`)*

---

## 🚀 快速开始

### 环境要求

- **Windows 10 1903+** / Windows 11(毛玻璃效果需要 DWM 支持)
- **Python 3.10+**
- 其他平台(macOS / Linux)可运行,但无毛玻璃效果,回退为半透明背景

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/moshuai1013/WebDownload.git
cd WebDownload

# 2. 安装依赖
pip install -r requirements.txt

# 3. 项目可以通过运行mkenv.bat文件或者mkenv.sh文件进行自动安装 Chromium(Tools/chromium-1140/),
#    如需自行安装 Playwright 浏览器:
# playwright install chromium
```

**requirements.txt** 包含:

| 依赖 | 最低版本 | 用途 |
|------|----------|------|
| `PySide6` | 6.5.0+ | Qt6 GUI 框架(主窗口/自绘控件/信号槽) |
| `playwright` | 1.40.0+ | 真浏览器渲染扫描 |
| `httpx` | 0.25.0+ | 并发流式下载 |

### 运行

**Windows:**

**下载完后双击mkenv.bat文件**，进行下载必要工具，他会下载到同级别的Tools里面，不会下载到C盘
然后下载完后就可以正式开始使用了，方式如下：

```bash
# 方式一:双击 start.bat
start.bat

# 方式二:命令行
python main.py
```

---



**Linux / macOS:**

**下载完后执行mkenv.sh文件**，进行下载必要工具，他会下载到同级别的Tools里面，不会下载到C盘，执行指令为：
然后下载完后就可以正式开始使用了，方式如下：

```bash
bash mkenv.sh
```



```bash
chmod +x start.sh
./start.sh
```

---

## 📖 使用说明

### 基本流程

1. **输入网址** — 在顶部输入框填入要扫描的网址
2. **扫描资源** — 点击「扫描资源」,等待真浏览器加载并提取所有资源
3. **选择类型** — 用 iOS 开关勾选要下载的资源类型(图片/音频/视频/CSS/JS/HTML)
4. **开始下载** — 选择保存目录后点击「开始下载」

---

#### 具体使用过程



<strong style="color:red;">如果需要打开某个按钮，例如“图片”按钮，不是通过点击按钮，而是通过<u>点击文字末尾，例如"片"字</u>，这样就可以进行开关这个按钮了</strong>



### 需要登录的网站

点击「登录浏览器」会打开一个**有界面的** Chromium 窗口,手动完成登录后关闭窗口,登录态(Cookies)会自动保存。之后再扫描同一网站即可带着登录态抓取。

> 登录数据保存在 `userdata/` 目录,重复使用无需重新登录。

### 设置

点击标题栏右上角 **齿轮图标** 打开设置:

| 设置项 | 说明 |
|--------|------|
| 默认保存目录 | 留空则保存到程序目录下的 `downloads/` |
| 并发数量 | 同时下载的线程数(1–32) |
| 自定义图标 | 支持 `.png` / `.ico` / `.jpg`,留空用内置默认图标 |

配置保存在 `config.json`,可手动编辑。

---

## 🏗️ 项目结构

```
WebDownload/
├── main.py                 # 程序入口
├── start.bat               # Windows 启动脚本
├── start.sh                # Linux/macOS 启动脚本
├── config.json             # 用户配置(保存目录/并发数/图标)
│
├── core/                   # 核心业务逻辑
│   ├── scanner.py          #   Playwright 资源扫描器
│   ├── downloader.py       #   httpx 并发下载器
│   └── workers.py          #   QThread 后台线程封装
│
├── ui/                     # 界面层
│   ├── window.py           #   主窗口(布局/信号/玻璃背景)
│   ├── titlebar.py         #   自定义无边框标题栏
│   ├── widgets.py          #   自绘控件(Card/Button/Switch/Handle)
│   ├── settings.py         #   设置对话框
│   └── styles.py           #   全局 QSS 样式表
│
├── utils/                  # 工具层
│   ├── glass.py            #   Windows DWM 毛玻璃 API 封装
│   ├── config.py           #   JSON 配置读写
│   ├── icon.py             #   应用图标加载/生成
│   └── urlutils.py         #   URL 规范化/资源分类
│
├── Tools/
│   └── chromium-1140/      # 内置 Chromium 浏览器
│
├── userdata/               # Playwright 持久化数据(Cookies/登录态)
└── downloads/              # 默认下载目录(运行时自动创建)
```

---

## 🔧 技术实现

### 毛玻璃效果

Windows 的 DWM Acrylic / BlurBehind API 不支持分层窗口(`WS_EX_LAYERED`),而 Qt 的 `WA_TranslucentBackground` 会自动加上这个标志。解决流程:

1. 窗口创建后用 `SetWindowLongW` 去掉 `WS_EX_LAYERED`
2. 调用 `SetWindowCompositionAttribute` 启用 Acrylic 模糊
3. 回退到 `DwmExtendFrameIntoClientArea(-1)` + `DwmEnableBlurBehindWindow`
4. 设置 `WA_NoSystemBackground` 阻止 Qt 重新绘制覆盖模糊效果

### 资源扫描

扫描器(`core/scanner.py`)在真浏览器里执行两轮提取:

- **网络拦截**:监听所有 HTTP 响应,按 `content-type` 分类
- **DOM 提取**:注入 JS 脚本,遍历 `<img>` / `<audio>` / `<video>` / `<link>` / `<script>` / 计算样式背景图 / 懒加载占位属性

两轮结果合并去重,返回完整资源清单。

### 并发下载

下载器(`core/downloader.py`)使用 `httpx.Client` 共享连接池 + `ThreadPoolExecutor`:

- 连接复用,避免每文件重建 TCP/TLS
- 流式读取(`iter_bytes`),大文件不占内存
- 进度回调按时间节流(默认 0.12s),避免 Signal 刷屏拖慢 UI
- 取消时立即停止并删除半截文件

---

## ⚠️ 注意事项

- **Chromium 体积较大** — `Tools/chromium-1140/` 约 300MB,克隆时注意
- **毛玻璃仅限 Windows** — macOS/Linux 运行时回退为半透明渐变背景
- **遵守 robots.txt 与版权** — 本工具仅用于合法的个人资源备份与学习研究,请勿用于侵犯版权或违反目标网站服务条款的用途
- **登录数据** — `userdata/` 目录包含浏览器登录态,切勿提交到公开仓库

---

## 📜 许可证

本项目采用 [MIT License](LICENSE) 开源。

---

## 📧 联系方式

如有问题，可以通过邮箱咨询，欢迎大家进行咨询

- **Email**: moshuai1013@outlook.com

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

1. Fork 本仓库
2. 创建你的分支(`git checkout -b feature/amazing-feature`)
3. 提交修改(`git commit -m 'Add amazing feature'`)
4. 推送到分支(`git push origin feature/amazing-feature`)
5. 开一个 Pull Request


# Ant Colony 安装引导

> 写给完全不懂技术的小白用户 | [English Version](installation-guide.en.md)

---

## 本指南适合谁看？

如果你没写过代码、没用过命令行、不懂什么是服务器——没关系，这份指南会**手把手**带你装好 Ant Colony。

**全程预计时间：20-30 分钟**

---

## 一、你需要准备什么？

### 1.1 一台电脑或服务器

| 你用什么系统？ | 说明 |
|---------------|------|
| **Linux（推荐）** | 最顺畅，自动安装。Ubuntu 20.04+/Debian 11+ |
| **macOS** | 也可以用，需要安装 Homebrew |
| **Windows** | 可以但不推荐。部分步骤需要手动操作 |

### 1.2 Python 3.10 或更高版本

验证方法：打开终端（或命令提示符），输入：

```bash
python --version
```

如果显示 `Python 3.10.x` 或更高，就 OK。

如果没有，去 [python.org](https://www.python.org/downloads/) 下载安装。

### 1.3 PostgreSQL 数据库

Ant Colony 需要一个 PostgreSQL 数据库来存储知识库和记忆体。安装脚本会自动帮你配置：

- **Linux**：自动安装
- **macOS**：自动用 Homebrew 安装
- **Windows**：需要手动下载安装（脚本会引导你）

### 1.4 至少一个聊天平台的开发者账号

你需要有权限在你公司的聊天平台上创建应用。以下是需要的：

<details>
<summary><b>📱 企业微信（推荐）</b></summary>

需要去企业微信管理后台创建应用：
1. 登录 [企微管理后台](https://work.weixin.qq.com/wework_admin/frame)
2. 左侧菜单 → 应用管理 → 创建应用
3. 填写应用名称（如「AI助手」）
4. 创建后拿到 **CorpID**、**AgentId**、**Secret**
</details>

<details>
<summary><b>📱 飞书 / Lark</b></summary>

1. 打开 [飞书开发者后台](https://open.feishu.cn)
2. 创建企业自建应用
3. 在「凭证与基础信息」获取 **App ID** 和 **App Secret**
</details>

<details>
<summary><b>📱 钉钉</b></summary>

1. 打开 [钉钉开发者后台](https://open-dev.dingtalk.com)
2. 创建应用
3. 获取 **Client ID** 和 **Client Secret**
</details>

<details>
<summary><b>📱 Telegram</b></summary>

1. 在 Telegram 中搜索 @BotFather
2. 发送 /newbot 创建机器人
3. 复制 BotFather 给你的 **Token**
</details>

---

## 二、安装步骤

### 第 1 步：下载代码

打开终端（macOS/Linux）或命令提示符（Windows），输入：

```bash
git clone https://github.com/[你的用户名]/ant-colony.git
cd ant-colony
```

> 如果不会用 git，也可以直接去 GitHub 页面下载 ZIP 文件，解压后进入文件夹。

### 第 2 步：运行安装脚本

```bash
python scripts/setup.py
```

安装脚本会一步步引导你完成：

```
1. 选择语言 → 中文
2. 检查 Python 版本
3. 安装依赖包（自动下载 PyMuPDF、python-docx 等）
4. 配置 AI 模型 → 输入你的 API Key
5. 配置聊天平台 → 输入刚刚拿到的凭证
6. 安装 PostgreSQL → 自动或手动
7. 设置第一个管理员 → 输入你的姓名
8. 初始化数据库
```

安装过程中，脚本会在需要你操作的地方停下来，告诉你**在哪里找什么参数**。

### 第 3 步：启动系统

```bash
python run_gateway.py
```

看到类似下面这样的输出，就说明启动成功了：

```
INFO:gateway webhook on 0.0.0.0:18090
```

---

## 三、验证

### 3.1 验证 AI 助手在线

在你的企业微信中找到你创建的 AI 机器人，发送一条消息：

```
你好
```

如果 AI 回复了，说明安装成功 🎉

### 3.2 添加自己为管理员

在聊天中发送：

```
添加管理员 [你的姓名]
```

例如：`添加管理员 张三`

---

## 四、常见问题

### Q：安装脚本报错了怎么办？

大多数错误是因为网络问题（下载超时）或缺少依赖。可以尝试：

```bash
pip install PyMuPDF python-docx python-pptx openpyxl httpx
```

然后重新运行安装脚本。

### Q：端口被占用了怎么办？

修改 `run_gateway.py` 文件中的端口号（把 `18090` 改成其他数字，比如 `18091`）。

### Q：启动后机器人没反应？

检查以下可能的原因：
1. 企业微信中是否有正确的回调 URL 配置
2. API Key 是否正确
3. 数据库是否已启动

### Q：如何停止系统？

在终端中按 `Ctrl + C`。

### Q：如何后台运行？

Linux 上推荐使用 systemd：

```bash
sudo cp infra/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start ant-colony-gateway
```

---

## 五、下一步

安装完成后，建议阅读 [使用手册](user-manual.md) 了解所有功能。

你也可以直接开始和 AI 助手对话——像和朋友聊天一样说出你的需求，它会自动匹配最适合的角色和工具来帮助你。

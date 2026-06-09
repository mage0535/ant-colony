# Ant Colony Installation Guide

> Written for complete beginners | [中文版](installation-guide.md)

---

## Who is this guide for?

If you have never written code, used a command line, or know what a server is — this guide is for you. It will walk you through **step by step**.

**Estimated time: 20-30 minutes**

---

## 1. What You Need

### 1.1 A Computer or Server

| Your OS | Notes |
|---------|-------|
| **Linux (recommended)** | Ubuntu 20.04+ or Debian 11+. Automatic setup. |
| **macOS** | Works with Homebrew. |
| **Windows** | Possible but manual setup for some steps. |

### 1.2 Python 3.10+

Open a terminal (or command prompt) and type:

```bash
python --version
```

If it shows `Python 3.10.x` or higher, you're good.

If not, download from [python.org](https://www.python.org/downloads/).

### 1.3 PostgreSQL Database

Ant Colony needs PostgreSQL for its knowledge base and memory. The setup script will handle installation:

- **Linux**: Automatic installation
- **macOS**: Automatic via Homebrew
- **Windows**: Manual download (script will guide you)

### 1.4 At Least One IM Platform Developer Account

You need access to create an app on your company's chat platform:

<details>
<summary><b>📱 WeCom (WeChat Work)</b></summary>

1. Open [WeCom Admin Console](https://work.weixin.qq.com/wework_admin/frame)
2. Menu → App Management → Create App
3. Set name (e.g., "AI Assistant")
4. After creating, copy the **CorpID**, **AgentId**, and **Secret**
</details>

<details>
<summary><b>📱 Feishu / Lark</b></summary>

1. Open [Feishu Developer Console](https://open.feishu.cn)
2. Create a self-built enterprise app
3. Get **App ID** and **App Secret** from credentials page
</details>

<details>
<summary><b>📱 DingTalk</b></summary>

1. Open [DingTalk Developer Console](https://open-dev.dingtalk.com)
2. Create an app
3. Get **Client ID** and **Client Secret**
</details>

<details>
<summary><b>📱 Telegram</b></summary>

1. In Telegram, search for @BotFather
2. Send /newbot to create a bot
3. Copy the **Token** from BotFather
</details>

---

## 2. Installation Steps

### Step 1: Clone the Code

Open a terminal and run:

```bash
git clone https://github.com/[your-username]/ant-colony.git
cd ant-colony
```

> Don't know git? Download the ZIP from the GitHub page, then extract it.

### Step 2: Run the Setup Wizard

```bash
python scripts/setup.py
```

The wizard will guide you through:

```
1. Select language → English
2. Check Python version
3. Install packages (PyMuPDF, python-docx, etc.)
4. Configure AI model → enter your API Key
5. Configure chat platform → enter your credentials
6. Install PostgreSQL → automatic or manual
7. Set first admin → enter your name
8. Initialize database
```

### Step 3: Start the System

```bash
python run_gateway.py
```

You should see:

```
INFO:gateway webhook on 0.0.0.0:18090
```

---

## 3. Verification

### 3.1 Check Bot is Online

In your chat app, find the AI bot you created and send:

```
Hello
```

If the AI replies, installation is successful 🎉

### 3.2 Add Yourself as Admin

Send:

```
添加管理员 [你的姓名]
```

Example: `添加管理员 John Smith`

---

## 4. Troubleshooting

### Q: The setup script fails?

Most errors are network timeouts. Try installing packages manually:

```bash
pip install PyMuPDF python-docx python-pptx openpyxl httpx
```

Then re-run the setup.

### Q: Port is in use?

Edit `run_gateway.py` and change `18090` to another number.

### Q: Bot is not responding?

Check:
1. Is the callback URL correctly configured in your IM platform?
2. Is the API Key correct?
3. Is the database running?

### Q: How to stop?

Press `Ctrl + C` in the terminal.

### Q: How to run in background?

On Linux, use systemd:

```bash
sudo cp infra/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start ant-colony-gateway
```

---

## 5. Next Steps

Read the [User Manual](user-manual.md) to learn all features.

Or just start talking to your AI assistant — it will automatically pick the best tools to help you.

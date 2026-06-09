"""
Ant Colony — Enterprise Multi-Agent Collaboration System
Multilingual bootstrap installer (中文 / English)

Usage:
    python scripts/setup.py              # Interactive install
    python scripts/setup.py --help       # See all options

This script guides you through:
  1. Language selection (中文 / English)
  2. Python environment check
  3. Package dependency installation
  4. LLM model configuration (DeepSeek / OpenAI / Anthropic / others)
  5. Platform configuration (WeCom / Feishu / DingTalk / Telegram)
   6. PostgreSQL + gbrain (knowledge base & memory, required)
   7. Organization structure setup
   8. Initial admin user setup
   9. Systemd / service installation (Linux)
  10. Final verification and tool inventory
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ────────────────────────────────────────────────────────────────
#  I18N — internationalization strings
# ────────────────────────────────────────────────────────────────

LANG: dict[str, dict[str, str]] = {}

def _load_lang():
    global LANG
    LANG = {
        "zh": {
            "title": "Ant Colony 企业多智能体协作系统 — 安装向导",
            "lang_prompt": "请选择语言 / Please select language:",
            "lang_zh": "中文",
            "lang_en": "English",
            "welcome": """
╔══════════════════════════════════════════════════════╗
║       Ant Colony — 企业多智能体协作系统安装向导       ║
║       让每个员工拥有自己的 AI 助手                      ║
╚══════════════════════════════════════════════════════╝

本向导将帮助你完成 Ant Colony 的安装和配置。
预计耗时：10-15 分钟

请确保：
  · 你有 Python 3.10 或更高版本
  · 你能连接互联网（下载依赖包）
  · 你有对应平台的开发者权限（申请 API 密钥）
""",
            "check_python": "检查 Python 版本...",
            "python_ok": "Python {0}.{1}.{2} — 符合要求",
            "python_fail": "需要 Python 3.10+，当前为 {0}.{1}.{2}",
            "create_dirs": "创建项目目录结构...",
            "install_deps": "安装核心依赖包...",
            "install_ok": "✓ {0} 安装成功",
            "install_fail": "✗ {0} 安装失败: {1}",
            "opt_packages": "可选依赖包（需要时再安装）:",
            "config_model": "\n╔══════════════════════════════════════════╗\n║  第一步：配置 AI 模型                      ║\n╚══════════════════════════════════════════╝\n\nAI 助手需要一个大语言模型来工作。你可以选择以下服务商：\n\n  1) DeepSeek（推荐，性价比高，国内可直接访问）\n  2) OpenAI（GPT 系列，需要海外网络）\n  3) Anthropic（Claude 系列，需要海外网络）\n  4) 其他兼容服务商（自定义 API 地址）\n",
            "model_prompt": "请选择模型服务商 (1-4): ",
            "model_choice_invalid": "请输入 1-4",
            "api_key_prompt": "请输入你的 API Key: ",
            "api_base_prompt": "请输入 API 地址（留空使用默认）: ",
            "model_name_prompt": "请输入模型名称（留空使用默认 {0}）: ",
            "model_verify": "验证 API Key 是否有效...",
            "model_ok": "✓ 模型配置完成，API Key 验证通过",
            "model_skip": "跳过模型配置，可以在 data/runtime_settings.json 中手动配置",
            "config_platform": "\n╔══════════════════════════════════════════╗\n║  第二步：配置聊天平台                      ║\n╚══════════════════════════════════════════╝\n\n你想通过哪个平台使用 AI 助手？（可以多选，用逗号分隔）\n  1) 企业微信 WeCom\n  2) 飞书 Feishu (中国版)\n     Lark (国际版)\n  3) 钉钉 DingTalk\n  4) Telegram\n  0) 跳过，以后配置\n",
            "platform_prompt": "请选择平台 (0-4): ",
            "config_wecom": "\n--- 企业微信配置 ---\n",
            "wecom_guide": """
配置企业微信 AI 机器人需要以下步骤：

1. 打开企业微信管理后台：https://work.weixin.qq.com/wework_admin/frame
2. 左侧菜单 → 「应用管理」→ 「创建应用」
3. 填写应用信息：
   · 应用名称：如「AI助手」
   · 应用说明：可选
4. 创建成功后，复制以下信息回来填写：
""",
            "wecom_corp_id": "请输入企业微信 CorpID: ",
            "wecom_corp_id_guide": "在哪找 CorpID？登录后台 → 「我的企业」→ 底部「企业ID」",
            "wecom_agent_id": "请输入 AgentId: ",
            "wecom_agent_id_guide": "在哪找 AgentId？「应用管理」→ 点击你的应用 → 顶部 AgentId",
            "wecom_secret": "请输入应用的 Secret: ",
            "wecom_secret_guide": "在哪找 Secret？「应用管理」→ 点击你的应用 → Secret → 查看",
            "wecom_callback_token": "请输入回调 Token（可选，留空跳过）: ",
            "wecom_aes_key": "请输入回调 EncodingAESKey（可选）: ",
            "wecom_contact_secret": "请输入通讯录同步 Secret（可选）: ",
            "wecom_verify": "验证企业微信配置...",
            "wecom_ok": "✓ 企业微信配置成功！找到了 {0} 个部门，{1} 个成员",
            "wecom_fail": "验证失败：{0}",
            "config_feishu": "\n--- 飞书配置 ---\n",
            "feishu_guide": """
配置飞书机器人步骤：

1. 打开飞书开发者后台：https://open.feishu.cn
2. 创建企业自建应用
3. 在「凭证与基础信息」中获取 App ID 和 App Secret
4. 在「事件与回调」中配置回调地址
""",
            "feishu_app_id": "请输入飞书 App ID: ",
            "feishu_app_secret": "请输入飞书 App Secret: ",
            "feishu_domain": "请选择版本 (cn=中国版 / intl=国际版Lark): ",
            "feishu_verify": "验证飞书配置...",
            "feishu_ok": "✓ 飞书配置成功",
            "feishu_fail": "验证失败：{0}",
            "config_dingtalk": "\n--- 钉钉配置 ---\n",
            "dingtalk_guide": """
配置钉钉机器人步骤：

1. 打开钉钉开发者后台：https://open-dev.dingtalk.com
2. 创建应用
3. 在「凭证与基本信息」中获取 Client ID 和 Client Secret
""",
            "dingtalk_client_id": "请输入钉钉 Client ID (AppKey): ",
            "dingtalk_client_secret": "请输入钉钉 Client Secret (AppSecret): ",
            "dingtalk_verify": "验证钉钉配置...",
            "dingtalk_ok": "✓ 钉钉配置成功",
            "dingtalk_fail": "验证失败：{0}",
            "config_telegram": "\n--- Telegram 配置 ---\n",
            "telegram_guide": """
配置 Telegram 机器人步骤：

1. 在 Telegram 中搜索 @BotFather
2. 发送 /newbot 创建新机器人
3. 复制 BotFather 给你的 Token
""",
            "telegram_token": "请输入 Telegram Bot Token: ",
            "telegram_verify": "验证 Telegram 配置...",
            "telegram_ok": "✓ Telegram 配置成功！机器人已上线",
            "telegram_fail": "验证失败：{0}",
            "config_admin": "\n╔══════════════════════════════════════════╗\n║  第三步：设置初始管理员                    ║\n╚══════════════════════════════════════════╝\n\n现在设置第一个企业管理员。管理员可以管理 AI 助手的配置、\n添加其他管理员、管理知识库和云盘。\n",
            "admin_name": "请输入你的姓名（作为第一个管理员）: ",
            "admin_find": "在企业微信通讯录中查找你的信息...",
            "admin_found": "找到你的账户：{0} (UserID: {1})",
            "admin_not_found": "未在企业微信中找到该姓名。你可以稍后在聊天中说「添加管理员 [姓名]」来添加自己。",
            "admin_ok": "✓ 已添加 {0} 为企业管理员",
            "config_init_db": "\n初始化数据库...",
            "db_ok": "✓ 数据库初始化完成",
            "config_done": """
╔══════════════════════════════════════════╗
║  安装完成！                              ║
╚══════════════════════════════════════════╝

启动 AI 助手：

  python run_gateway.py

启动后，在你的企微里找到 AI 机器人，发送一条消息测试。

常见问题：
  · 如果启动时报错端口被占用，修改 run_gateway.py 中的端口号
  · 如果模型连接失败，检查 data/runtime_settings.json 中的 API Key
  · 详细文档见 docs/user-manual.md
  · 完整工具清单在安装日志中
""",
            "any_key": "按回车键继续...",
            "yes_no": "(y/n): ",
            "yes": "y",
            "no": "n",
        },
        "en": {
            "title": "Ant Colony — Enterprise Multi-Agent System Setup",
            "lang_prompt": "Please select language:",
            "lang_zh": "Chinese",
            "lang_en": "English",
            "welcome": """
╔══════════════════════════════════════════════════════╗
║       Ant Colony — Enterprise Multi-Agent System     ║
║          Setup Wizard                                ║
╚══════════════════════════════════════════════════════╝

This wizard will help you install and configure Ant Colony.
Estimated time: 10-15 minutes

Prerequisites:
  · Python 3.10 or higher
  · Internet connection (to download packages)
  · Developer account on your chosen IM platform
""",
            "check_python": "Checking Python version...",
            "python_ok": "Python {0}.{1}.{2} — OK",
            "python_fail": "Python 3.10+ required, found {0}.{1}.{2}",
            "create_dirs": "Creating project directories...",
            "install_deps": "Installing core dependencies...",
            "install_ok": "✓ {0} installed",
            "install_fail": "✗ {0} failed: {1}",
            "opt_packages": "Optional packages (install when needed):",
            "config_model": "\n╔══════════════════════════════════════════╗\n║  Step 1: Configure AI Model               ║\n╚══════════════════════════════════════════╝\n\nAI assistant needs a LLM to work. Choose a provider:\n\n  1) DeepSeek (recommended, good value)\n  2) OpenAI (GPT series, requires overseas access)\n  3) Anthropic (Claude series)\n  4) Other (custom API endpoint)\n",
            "model_prompt": "Select model provider (1-4): ",
            "model_choice_invalid": "Please enter 1-4",
            "api_key_prompt": "Enter your API Key: ",
            "api_base_prompt": "Enter API base URL (leave empty for default): ",
            "model_name_prompt": "Enter model name (leave empty for default {0}): ",
            "model_verify": "Verifying API Key...",
            "model_ok": "✓ Model configured, API Key verified",
            "model_skip": "Skipping model config. You can manually edit data/runtime_settings.json later.",
            "config_platform": "\n╔══════════════════════════════════════════╗\n║  Step 2: Configure Chat Platform          ║\n╚══════════════════════════════════════════╝\n\nWhich platform do you want to use? (comma-separated for multiple)\n  1) WeCom (WeChat Work)\n  2) Feishu (Lark China)\n     Lark (International)\n  3) DingTalk\n  4) Telegram\n  0) Skip, configure later\n",
            "platform_prompt": "Select platform (0-4): ",
            "config_wecom": "\n--- WeCom Configuration ---\n",
            "wecom_guide": """
To configure WeCom AI bot:

1. Open WeCom admin console: https://work.weixin.qq.com/wework_admin/frame
2. Menu → 「App Management」→ 「Create App」
3. Fill in:
   · App name: e.g. 「AI Assistant」
   · Description: optional
4. After creating, copy the credentials below:
""",
            "wecom_corp_id": "Enter WeCom Corp ID: ",
            "wecom_corp_id_guide": "Where to find CorpID? Admin console → 「My Company」→ bottom of page → CorpID",
            "wecom_agent_id": "Enter Agent ID: ",
            "wecom_agent_id_guide": "Where to find AgentID? 「App Management」→ click your app → AgentId at top",
            "wecom_secret": "Enter App Secret: ",
            "wecom_secret_guide": "Where to find Secret? 「App Management」→ click your app → Secret → View",
            "wecom_callback_token": "Enter callback Token (optional, empty to skip): ",
            "wecom_aes_key": "Enter EncodingAESKey (optional): ",
            "wecom_contact_secret": "Enter contact sync Secret (optional): ",
            "wecom_verify": "Verifying WeCom configuration...",
            "wecom_ok": "✓ WeCom configured! Found {0} departments, {1} members",
            "wecom_fail": "Verification failed: {0}",
            "config_feishu": "\n--- Feishu Configuration ---\n",
            "feishu_guide": """
To configure Feishu/Lark bot:

1. Open Feishu developer console: https://open.feishu.cn
2. Create a self-built enterprise app
3. In 「Credentials & Basic Info」, copy the App ID and App Secret
4. Configure event callbacks
""",
            "feishu_app_id": "Enter Feishu App ID: ",
            "feishu_app_secret": "Enter Feishu App Secret: ",
            "feishu_domain": "Select version (cn=China / intl=Lark): ",
            "feishu_verify": "Verifying Feishu configuration...",
            "feishu_ok": "✓ Feishu configured successfully",
            "feishu_fail": "Verification failed: {0}",
            "config_dingtalk": "\n--- DingTalk Configuration ---\n",
            "dingtalk_guide": """
To configure DingTalk bot:

1. Open DingTalk developer console: https://open-dev.dingtalk.com
2. Create an application
3. In 「Credentials & Basic Info」, copy the Client ID and Client Secret
""",
            "dingtalk_client_id": "Enter DingTalk Client ID (AppKey): ",
            "dingtalk_client_secret": "Enter DingTalk Client Secret (AppSecret): ",
            "dingtalk_verify": "Verifying DingTalk configuration...",
            "dingtalk_ok": "✓ DingTalk configured successfully",
            "dingtalk_fail": "Verification failed: {0}",
            "config_telegram": "\n--- Telegram Configuration ---\n",
            "telegram_guide": """
To configure Telegram bot:

1. In Telegram, search for @BotFather
2. Send /newbot to create a new bot
3. Copy the token BotFather gives you
""",
            "telegram_token": "Enter Telegram Bot Token: ",
            "telegram_verify": "Verifying Telegram configuration...",
            "telegram_ok": "✓ Telegram bot is online!",
            "telegram_fail": "Verification failed: {0}",
            "config_admin": "\n╔══════════════════════════════════════════╗\n║  Step 3: Set Initial Admin                ║\n╚══════════════════════════════════════════╝\n\nSet the first enterprise admin. Admins can configure\nthe system, add other admins, and manage knowledge bases.\n",
            "admin_name": "Enter your name (as the first admin): ",
            "admin_find": "Searching for you in WeCom contacts...",
            "admin_found": "Found: {0} (UserID: {1})",
            "admin_not_found": "Name not found in WeCom. You can later add yourself via chat: 'add_admin [your name]'",
            "admin_ok": "✓ Added {0} as enterprise admin",
            "config_init_db": "\nInitializing database...",
            "db_ok": "✓ Database initialized",
            "config_done": """
╔══════════════════════════════════════════╗
║  Setup Complete!                         ║
╚══════════════════════════════════════════╝

Start your AI assistant:

  python run_gateway.py

After starting, find your AI bot in WeCom and send a message.

Troubleshooting:
  · Port in use? Edit the port in run_gateway.py
  · Model connection failed? Check data/runtime_settings.json
  · Full docs in docs/user-manual.md
""",
            "any_key": "Press Enter to continue...",
            "yes_no": "(y/n): ",
            "yes": "y",
            "no": "n",
        },
    }


def _(key: str) -> str:
    """Get localized string."""
    return LANG.get(active_lang, LANG["en"]).get(key, f"[{key}]")


# Detect terminal color support
_USE_COLOR = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


def color(text: str, code: str = "") -> str:
    if not _USE_COLOR or not code:
        return text
    codes = {"green": "32", "yellow": "33", "red": "31", "cyan": "36", "bold": "1"}
    c = codes.get(code, "")
    return f"\033[{c}m{text}\033[0m" if c else text


# ────────────────────────────────────────────────────────────────
#  Utility functions
# ────────────────────────────────────────────────────────────────

def confirm(msg: str) -> bool:
    resp = input(msg + _("yes_no")).strip().lower()
    return resp == _("yes") or resp == "y"


def pause():
    input(_("any_key"))


def print_step(step: str, detail: str = ""):
    print(f"\n  {color(step, 'cyan')}")
    if detail:
        for line in detail.split('\n'):
            if line.strip():
                print(f"    {line}")


def prompt(text: str, secret: bool = False) -> str:
    """Prompt for user input with optional secret mode."""
    if not sys.stdin.isatty():
        print(f"{text} (non-interactive, using defaults)")
        return ""
    try:
        import getpass
        if secret:
            return getpass.getpass(text)
        return input(text).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    except Exception:
        if secret:
            return getpass.getpass(text)
        return input(text).strip()


def prompt_with_guide(text: str, guide: str = "") -> str:
    if guide:
        print(f"\n    {color('提示', 'yellow')}: {guide}")
    return prompt(f"    {text}")


# ────────────────────────────────────────────────────────────────
#  Language selection
# ────────────────────────────────────────────────────────────────

def select_language() -> str:
    print()
    print("  " + _("lang_prompt"))
    print(f"    1. {_('lang_zh')}")
    print(f"    2. {_('lang_en')}")
    choice = prompt("  ").strip()
    return "zh" if choice == "1" else "en"


# ────────────────────────────────────────────────────────────────
#  System checks & dependencies
# ────────────────────────────────────────────────────────────────

def check_python() -> bool:
    print_step(_("check_python"))
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"    {color(_('python_fail').format(v.major, v.minor, v.micro), 'red')}")
        return False
    print(f"    {color(_('python_ok').format(v.major, v.minor, v.micro), 'green')}")
    return True


def setup_directories():
    print_step(_("create_dirs"))
    project_root = Path(__file__).resolve().parent.parent
    dirs = ["data/memory", "data/files", "data/backups", "data/cloud_sync"]
    for d in dirs:
        (project_root / d).mkdir(parents=True, exist_ok=True)
        print(f"    Created {d}/")


def install_packages():
    print_step(_("install_deps"))
    core_pkgs = ["PyMuPDF", "python-docx", "python-pptx", "openpyxl", "httpx"]
    for pkg in core_pkgs:
        print(f"    Installing {pkg}...", end=" ", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                capture_output=True, text=True, timeout=120
            )
            print(f"{color('OK', 'green')}")
        except Exception as e:
            print(f"{color(f'FAIL: {e}', 'red')}")

    print(f"\n    {_('opt_packages')}")
    for pkg, desc in [
        ("marker-pdf", "Advanced OCR (~5GB)"),
        ("dingtalk-stream", "DingTalk stream SDK"),
        ("lark-oapi", "Feishu SDK"),
        ("python-telegram-bot", "Telegram Bot SDK"),
    ]:
        print(f"      pip install {pkg}  # {desc}")


# ────────────────────────────────────────────────────────────────
#  LLM Model configuration
# ────────────────────────────────────────────────────────────────

def configure_model() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "data" / "runtime_settings.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    print(_("config_model"))

    providers = {
        "1": ("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
        "2": ("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
        "3": ("anthropic", "Anthropic", "https://api.anthropic.com", "claude-sonnet-4-20250514"),
        "4": ("openai_compatible", "Other", "", "gpt-4o-mini"),
    }

    while True:
        choice = prompt(_("model_prompt")).strip()
        if choice in providers:
            break
        print(f"    {color(_('model_choice_invalid'), 'yellow')}")

    provider_id, provider_name, default_base, default_model = providers[choice]

    api_key = ""
    while not api_key:
        api_key = prompt(_("api_key_prompt"), secret=True)
        if not api_key and not confirm(f"    {color('No API key entered. Continue anyway?', 'yellow')}"):
            continue
        break

    api_base = prompt(_("api_base_prompt").format(default_base)) or default_base
    model_name = prompt(_("model_name_prompt").format(default_model)) or default_model

    # Save configuration
    settings = {
        "llm_profiles": [{
            "profile_id": provider_id,
            "provider": provider_id,
            "model_name": model_name,
            "api_key": api_key,
            "api_base": api_base,
            "max_tokens": 8192,
            "timeout_seconds": 120,
            "enabled": True,
        }],
        "admin_settings": {
            "admin_user_ids": [],
            "web_default_password": "admin123",
            "pause_command_enabled": True,
            "handoff_command_enabled": False,
        },
    }

    # Verify
    if api_key and api_base:
        print(f"\n    {_('model_verify')}")
        try:
            req = urllib.request.Request(
                api_base.rstrip('/') + "/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"    {color(_('model_ok'), 'green')}")
        except Exception:
            print(f"    {color('Warning: Could not verify API. Check your key and try again.', 'yellow')}")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    return settings


# ────────────────────────────────────────────────────────────────
#  Platform configuration
# ────────────────────────────────────────────────────────────────

def configure_platforms() -> dict:
    print(_("config_platform"))

    platforms = {}
    choices = prompt(_("platform_prompt")).strip()

    if choices == "0":
        return platforms

    selected = set(c.strip() for c in choices.split(","))

    if "1" in selected:
        p = configure_wecom()
        if p:
            platforms.update(p)

    if "2" in selected:
        p = configure_feishu()
        if p:
            platforms.update(p)

    if "3" in selected:
        p = configure_dingtalk()
        if p:
            platforms.update(p)

    if "4" in selected:
        p = configure_telegram()
        if p:
            platforms.update(p)

    return platforms


def configure_wecom() -> dict:
    print(_("config_wecom"))
    print(_("wecom_guide"))
    pause()

    corp_id = prompt_with_guide(_("wecom_corp_id"), _("wecom_corp_id_guide"))
    if not corp_id:
        return {}

    agent_id = prompt_with_guide(_("wecom_agent_id"), _("wecom_agent_id_guide"))
    secret = prompt_with_guide(_("wecom_secret"), _("wecom_secret_guide"), secret=True)

    if not agent_id or not secret:
        print(f"    {color('AgentId and Secret are required. Skipping WeCom.', 'yellow')}")
        return {}

    callback_token = prompt_with_guide(_("wecom_callback_token"))
    aes_key = prompt_with_guide(_("wecom_aes_key"))
    contact_secret = prompt_with_guide(_("wecom_contact_secret"))

    # Verify
    print(f"\n    {_('wecom_verify')}")
    try:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            print(f"    {color(_('wecom_fail').format(data.get('errmsg', 'unknown')), 'red')}")
            return {}
        token = data.get("access_token", "")
        # Get dept/member count
        dept_url = f"https://qyapi.weixin.qq.com/cgi-bin/department/list?access_token={token}"
        with urllib.request.urlopen(dept_url, timeout=10) as resp:
            dept_data = json.loads(resp.read())
        dept_count = len(dept_data.get("department", []))
        user_url = f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id=1&fetch_child=1"
        with urllib.request.urlopen(user_url, timeout=10) as resp:
            user_data = json.loads(resp.read())
        user_count = len(user_data.get("userlist", []))
        print(f"    {color(_('wecom_ok').format(dept_count, user_count), 'green')}")
    except Exception as e:
        print(f"    {color(_('wecom_fail').format(str(e)), 'red')}")
        # Allow continuing with unverified config
        if not confirm("    Continue with unverified config?"):
            return {}

    return {
        "WECOM_CORP_ID": corp_id,
        "WECOM_AGENT_ID": agent_id,
        "WECOM_SECRET": secret,
        "WECOM_CALLBACK_TOKEN": callback_token,
        "WECOM_CALLBACK_AES_KEY": aes_key,
        "WECOM_CONTACT_SECRET": contact_secret,
    }


def configure_feishu() -> dict:
    print(_("config_feishu"))
    print(_("feishu_guide"))
    pause()

    app_id = prompt(_("feishu_app_id"))
    if not app_id:
        return {}
    app_secret = prompt(_("feishu_app_secret"), secret=True)
    domain = prompt(_("feishu_domain")).strip().lower() or "cn"

    print(f"\n    {_('feishu_verify')}")
    try:
        base = "https://open.feishu.cn" if domain == "cn" else "https://open.larksuite.com"
        url = f"{base}/open-apis/auth/v3/tenant_access_token/internal"
        req = urllib.request.Request(
            url, data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if "tenant_access_token" in data:
            print(f"    {color(_('feishu_ok'), 'green')}")
        else:
            print(f"    {color('Failed: ' + str(data), 'red')}")
            return {}
    except Exception as e:
        print(f"    {color(_('feishu_fail').format(str(e)), 'red')}")
        if not confirm("    Continue?"):
            return {}

    return {"FEISHU_APP_ID": app_id, "FEISHU_APP_SECRET": app_secret, "FEISHU_DOMAIN": domain}


def configure_dingtalk() -> dict:
    print(_("config_dingtalk"))
    print(_("dingtalk_guide"))
    pause()

    client_id = prompt(_("dingtalk_client_id"))
    if not client_id:
        return {}
    client_secret = prompt(_("dingtalk_client_secret"), secret=True)

    print(f"\n    {_('dingtalk_verify')}")
    try:
        url = f"https://oapi.dingtalk.com/gettoken?appkey={client_id}&appsecret={client_secret}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) == 0:
            print(f"    {color(_('dingtalk_ok'), 'green')}")
        else:
            print(f"    {color('Failed: ' + data.get('errmsg', ''), 'red')}")
            return {}
    except Exception as e:
        print(f"    {color(_('dingtalk_fail').format(str(e)), 'red')}")
        if not confirm("    Continue?"):
            return {}

    return {"DINGTALK_CLIENT_ID": client_id, "DINGTALK_CLIENT_SECRET": client_secret}


def configure_telegram() -> dict:
    print(_("config_telegram"))
    print(_("telegram_guide"))
    pause()

    token = prompt(_("telegram_token"))
    if not token:
        return {}

    print(f"\n    {_('telegram_verify')}")
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            bot_name = data["result"].get("first_name", "")
            print(f"    {color(_('telegram_ok').format(bot_name), 'green')}")
        else:
            print(f"    {color('Invalid token', 'red')}")
            return {}
    except Exception as e:
        print(f"    {color(_('telegram_fail').format(str(e)), 'red')}")
        return {}

    return {"TELEGRAM_BOT_TOKEN": token}


# ────────────────────────────────────────────────────────────────
#  Admin setup
# ────────────────────────────────────────────────────────────────

def configure_admin(env_config: dict):
    print(_("config_admin"))
    name = prompt(_("admin_name"))
    if not name:
        print(f"    {color('Skipping admin setup. You can add yourself later via: 添加管理员 [姓名]', 'yellow')}")
        return

    print(f"\n    {_('admin_find')}")
    try:
        if "WECOM_CORP_ID" in env_config and "WECOM_SECRET" in env_config:
            corp_id = env_config["WECOM_CORP_ID"]
            secret = env_config["WECOM_SECRET"]
            url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            token = data.get("access_token", "")

            dept_url = f"https://qyapi.weixin.qq.com/cgi-bin/department/list?access_token={token}"
            with urllib.request.urlopen(dept_url, timeout=10) as resp:
                depts = json.loads(resp.read())

            found = None
            for d in depts.get("department", []):
                user_url = f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id={d['id']}&fetch_child=1"
                with urllib.request.urlopen(user_url, timeout=10) as resp:
                    users = json.loads(resp.read())
                for u in users.get("userlist", []):
                    if u.get("name", "") == name:
                        found = u
                        break
                if found:
                    break

            if found:
                userid = found["userid"]
                print(f"    {color(_('admin_found').format(name, userid), 'green')}")

                # Add to admin registry via SQLite
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from src.platform.admin_registry import add_admin
                add_admin("wecom", userid, name, "bootstrap")
                print(f"    {color(_('admin_ok').format(name), 'green')}")
            else:
                print(f"    {color(_('admin_not_found'), 'yellow')}")
        else:
            print(f"    {color('WeCom not configured, skipping admin auto-setup.', 'yellow')}")
            print(f"    {color('After starting, say: 添加管理员 {0}'.format(name), 'cyan')}")
    except Exception as e:
        print(f"    {color('Admin setup error: {0}, you can add manually later'.format(str(e)), 'yellow')}")


# ────────────────────────────────────────────────────────────────
#  Write env file
# ────────────────────────────────────────────────────────────────

def write_env_file(config: dict):
    project_root = Path(__file__).resolve().parent.parent
    env_file = project_root / "infra" / ".env.wecom"
    env_file.parent.mkdir(parents=True, exist_ok=True)

    with open(env_file, "w", encoding="utf-8") as f:
        f.write("# Ant Colony - Platform Credentials\n")
        f.write("# Generated by setup.py\n\n")
        for key, value in sorted(config.items()):
            if value:
                f.write(f"{key}={value}\n")

    os.chmod(env_file, 0o600)
    print(f"\n    Credentials saved to {env_file}")


# ────────────────────────────────────────────────────────────────
#  Database init
# ────────────────────────────────────────────────────────────────

def setup_knowledge_base():
    """Required: PostgreSQL + gbrain for knowledge graph + ACL memory."""
    print(f"\n  {color('=== Knowledge Base & Memory System (Required)', 'cyan')}")
    print("""
    Ant Colony requires PostgreSQL 16+ with pgvector extension for:
    - Knowledge base with ACL (access control)
    - Agent memory (gbrain knowledge graph)
    - Semantic search (vector embeddings)
    - Hindsight (warm memory recall)

    Without PostgreSQL, the system will NOT start correctly.
    """)

    project_root = Path(__file__).resolve().parent.parent
    import platform as _platform
    os_name = _platform.system().lower()

    if os_name == "linux":
        print("    Detected: Linux — installing PostgreSQL...\n")
        try:
            cmds = [
                "sudo apt-get update -qq",
                "sudo apt-get install -y -qq postgresql postgresql-contrib postgresql-16-pgvector 2>/dev/null || "
                "sudo apt-get install -y -qq postgresql postgresql-contrib",
                "sudo systemctl start postgresql 2>/dev/null; sudo systemctl enable postgresql 2>/dev/null",
            ]
            for cmd in cmds:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
                if result.returncode != 0 and "already" not in result.stderr:
                    pass  # Continue despite minor errors

            # Create database and user
            sql_cmds = [
                'sudo -u postgres psql -c "CREATE USER sidecar WITH PASSWORD \'sidecar123\';" 2>/dev/null',
                'sudo -u postgres psql -c "CREATE DATABASE sidecar OWNER sidecar;" 2>/dev/null',
                'sudo -u postgres psql -d sidecar -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null',
                'sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE sidecar TO sidecar;" 2>/dev/null',
            ]
            for cmd in sql_cmds:
                subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            # Verify
            import psycopg2
            conn = psycopg2.connect("postgresql://sidecar:sidecar123@localhost:5432/sidecar")
            conn.close()
            print(f"    {color('PostgreSQL installed and connected OK', 'green')}")
        except ImportError:
            print("    Installing psycopg2...")
            subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary", "--quiet"],
                           capture_output=True, text=True, timeout=60)
        except Exception as e:
            print(f"    {color('PostgreSQL setup error: ' + str(e), 'yellow')}")
            print(f"    Please install PostgreSQL manually, then re-run this script.")
            print(f"    https://www.postgresql.org/download/")
            input("    Press Enter after installing PostgreSQL...")
            return

    elif os_name == "darwin":
        print("    Detected: macOS — installing PostgreSQL via Homebrew...")
        try:
            subprocess.run("brew install postgresql@16 pgvector", shell=True, capture_output=True, text=True, timeout=120)
            subprocess.run("brew services start postgresql@16", shell=True, capture_output=True, text=True, timeout=30)
            # Create user and DB
            for cmd in [
                '/usr/local/opt/postgresql@16/bin/createuser -s sidecar 2>/dev/null || '
                '/opt/homebrew/opt/postgresql@16/bin/createuser -s sidecar 2>/dev/null || true',
                'createdb -O sidecar sidecar 2>/dev/null || true',
            ]:
                subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            import psycopg2
            conn = psycopg2.connect("postgresql://sidecar:sidecar123@localhost:5432/sidecar")
            conn.close()
            print(f"    {color('PostgreSQL installed and connected', 'green')}")
        except Exception as e:
            print(f"    {color('macOS PostgreSQL: ' + str(e), 'yellow')}")
            print("    Run: brew install postgresql@16 pgvector")
            input("    Press Enter after installing PostgreSQL...")
    else:
        print(f"    Detected: Windows")
        print(f"""
    PostgreSQL is required. Please install it manually:

    1. Download PostgreSQL 16+ from:
       https://www.postgresql.org/download/windows/

    2. During installation:
       - Set password for postgres user (remember it)
       - Keep default port 5432

    3. After installation, open "SQL Shell (psql)" and run:
       CREATE USER sidecar WITH PASSWORD 'sidecar123';
       CREATE DATABASE sidecar OWNER sidecar;
       \\c sidecar
       CREATE EXTENSION vector;

    4. Also install pgvector:
       https://github.com/pgvector/pgvector#windows
""")
        input("    Press Enter after installing PostgreSQL...")

    # Install psycopg2 and init gbrain
    try:
        import psycopg2
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary", "--quiet"],
                       capture_output=True, text=True, timeout=60)
        print("    psycopg2 installed")

    # Initialize gbrain tables
    try:
        sys.path.insert(0, str(project_root))
        from src.memory.gbrain_bridge import init_db as init_gbrain
        init_gbrain()
        print(f"    {color('gbrain + hindsight tables created in PostgreSQL', 'green')}")
    except Exception as e:
        print(f"    gbrain init: {e} (will init on first gbrain start)")

    # Also init hindsight
    try:
        from src.memory.hindsight_bridge import init_db as init_hindsight
        init_hindsight()
        print(f"    {color('hindsight tables created', 'green')}")
    except Exception:
        pass

    print(f"    {color('Knowledge base & memory system ready', 'green')}")
    print(f"""
    Start gbrain:     python -m src.memory.gbrain_bridge
    Start hindsight:  python -m src.memory.hindsight_bridge
    Or via systemd:   sudo systemctl start gbrain-bridge hindsight-bridge
    """)


def init_database():
    """Initialize SQLite database and create all required tables."""
    print_step(_("config_init_db"))
    try:
        project_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(project_root))
        from src.store.database import Database
        from src.knowledge.cloud_drive import _ensure_table
        from src.platform.admin_registry import _ensure_table as _ensure_admin_table

        db = Database.get(str(project_root / "data" / "ant-colony.db"))
        conn = db.connect()

        # Create cloud_drives table
        _ensure_table()

        # Create platform_admins table  
        _ensure_admin_table()

        # Create knowledge_items + FTS tables
        from src.knowledge.fts_repo import FtsKnowledgeRepository
        repo = FtsKnowledgeRepository(conn)

        # Create task tables (via TaskRepository init)
        from src.store.task_repo import TaskRepository
        task_repo = TaskRepository(db)

        # Create cron_jobs table
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    command TEXT NOT NULL,
                    no_agent INTEGER NOT NULL DEFAULT 1,
                    tags TEXT NOT NULL DEFAULT '[]',
                    last_run_at REAL DEFAULT 0,
                    last_result TEXT DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.commit()
        except Exception:
            pass

        # Initialize gbrain PostgreSQL tables (if PostgreSQL is available)
        try:
            from src.memory.gbrain_bridge import init_db as init_gbrain
            init_gbrain()
            print(f"    gbrain tables initialized (PostgreSQL)")
        except Exception:
            pass

        conn.close()
        print(f"    {color(_('db_ok'), 'green')}")
    except Exception as e:
        print(f"    Database init: {e} (will init on first start)")


def print_tool_inventory():
    """Output complete registered tool list."""
    try:
        project_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(project_root))
        from src.tools.builtin import BUILTIN_TOOLS

        print(f"\n  {color('=== Registered Tools: ' + str(len(BUILTIN_TOOLS)) + ' total ===', 'cyan')}")
        from collections import defaultdict
        cats = defaultdict(list)
        for t in BUILTIN_TOOLS:
            cats[t.category].append(t.name)

        for cat in sorted(cats):
            tools = cats[cat]
            print(f"    [{cat}] {', '.join(tools[:5])}" + ("..." if len(tools) > 5 else ""))
        print(f"    Total: {len(BUILTIN_TOOLS)} tools in {len(cats)} categories")
    except Exception as e:
        print(f"    Tool inventory: {e}")
    print_step(_("config_init_db"))
    try:
        project_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(project_root))
        from src.store.database import Database
        db = Database.get(str(project_root / "data" / "ant-colony.db"))
        conn = db.connect()
        from src.knowledge.cloud_drive import _ensure_table
        _ensure_table()
        conn.close()
        print(f"    {color(_('db_ok'), 'green')}")
    except Exception as e:
        print(f"    Database init: {e} (will init on first start)")


# ────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────

def main():
    global active_lang
    active_lang = "en"  # default

    # Print title
    _load_lang()

    # Language selection
    active_lang = select_language()
    _load_lang()

    # Welcome
    print(_("welcome"))
    pause()

    # 1. Python check
    if not check_python():
        sys.exit(1)

    # 2. Create directories
    setup_directories()

    # 3. Install packages
    install_packages()
    pause()

    # 4. Configure model
    model_config = configure_model()

    # 5. Configure platform
    env_config = configure_platforms()

    # 6. Save env config
    if env_config:
        write_env_file(env_config)
    else:
        print(f"\n    {color('No platforms configured. You can add them later.', 'yellow')}")

    # 7. Setup admin
    configure_admin(env_config)

    # 8. Init database
    init_database()

    # 9. Knowledge base + memory (PostgreSQL + gbrain, required)
    setup_knowledge_base()

    # 10. Tool inventory
    print_tool_inventory()

    # Done
    print(_("config_done"))


if __name__ == "__main__":
    main()

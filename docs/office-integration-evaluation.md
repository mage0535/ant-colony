# Office 文档本地集成项目选型评估

## 结论先行

对当前项目，最合适的本地 Office 文档主后端选择是：

- **主推荐：OfficeCLI**
- **协作式文档补充：ONLYOFFICE Docs**
- **基础库继续保留：python-docx / openpyxl / python-pptx**

不推荐把“微软官方云侧 Office AI 技能体系”作为当前主落地方向。

## 选型判断依据

当前项目约束是：

1. Bot First, Capability Backend
2. 企业级文档处理默认本地私有部署
3. 需要支持 `docx/xlsx/pptx` 的程序化生成与处理
4. 更适合服务企业 IM Bot，而不是先做协作文档前端
5. 要兼容当前 Python 主栈

## 候选对象

### 1. OfficeCLI

特点：

- 面向 AI / Agent 的 Office 文档操作
- 覆盖 `docx/xlsx/pptx`
- 与当前项目现有 `document_tool.py` 已直接集成
- 更适合作为 Bot 背后的本地文档能力后端

综合评价：

- 功能适配度：高
- 本地集成难度：低
- 与现有代码兼容度：最高
- 后续维护成本：低

结论：

- **当前项目最适合作为主 Office 后端**

### 2. ONLYOFFICE Docs

特点：

- 本地私有部署成熟
- 更强的在线协作、预览、编辑能力
- 更偏“协作文档服务”

综合评价：

- 协作能力：强
- 作为当前 Bot 后端直接主链：中
- 集成复杂度：中高

结论：

- 适合作为中长期补充
- 不适合作为当前第一主线替代 OfficeCLI

### 3. Microsoft 官方 Office AI / Skills 相关能力

特点：

- 官方生态强
- 与 Microsoft 365 体系融合度高
- 更偏云侧 / SaaS / Copilot 生态

综合评价：

- 官方生态价值：高
- 本地私有部署适配：弱
- 当前项目可直接集成度：低

结论：

- 可作为研究参考
- **不适合作为当前主实现**

### 4. python-docx / openpyxl / python-pptx

特点：

- 轻量
- Python 原生
- 当前项目已经部分使用

结论：

- 继续保留
- 更适合作为底层补充，而不是统一能力后端的唯一长期方案

## 当前建议

### 短期

- 将 `OfficeCLI` 正式确认为本地 Office 主后端
- 统一能力协议围绕 `files.docx.* / files.xlsx.* / files.pptx.*` 继续扩展

### 当前最新进展

项目内已补齐：

- `files.office.service_status`
- `files.docx.generate`
- `files.docx.read`
- `files.docx.template_outline`
- `files.xlsx.generate`
- `files.xlsx.read`
- `files.xlsx.template_outline`
- `files.pptx.generate`
- `files.pptx.read`
- `files.pptx.template_outline`

说明：

- Office 文档能力已进入统一能力后端第一版实现
- 当前不再只是底层库分散调用，而是已有协议化入口

### 中期

- 若需要在线协作 / 预览 / 编辑，再评估接入 `ONLYOFFICE Docs`

### 长期

- 保持：
  - OfficeCLI = 结构化 Office 文档处理主后端
  - ONLYOFFICE = 协作增强
  - Python 基础库 = 兜底与细粒度能力补充

## 当前项目结论

| 项目 | 角色 |
|------|------|
| OfficeCLI | 主 Office 文档后端推荐 |
| ONLYOFFICE Docs | 协作式文档服务补充 |
| Microsoft Office AI / Skills | 研究参考，不作为当前主实现 |
| python-docx / openpyxl / python-pptx | 本地底层补充 |

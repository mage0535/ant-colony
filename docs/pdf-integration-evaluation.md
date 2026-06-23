# PDF 集成项目选型评估

## 背景

当前项目已经把 PDF 能力开始纳入统一能力后端，但现阶段仍主要依赖本地 Python 工具链：

- `PyMuPDF` / `fitz`
- 自建 `pdf_tool.py`

这适合快速起步，但如果要进一步覆盖：

- 更多 PDF 操作种类
- 更成熟的 REST API
- 更完整的自动化流水线
- 更低的后续维护成本

则应评估是否引入成熟的现成开源项目作为 PDF 能力后端。

## 企业级约束（新增）

对当前项目，文档处理能力默认应满足以下约束：

1. **本地私有部署优先**
   - 文档处理默认跑在企业内网服务器
   - 不依赖公网托管 API 作为主处理链路
2. **支持高并发与批量同步**
   - 要考虑大量文档持续入库
   - 要支持并发解析、批处理、自动流水线
3. **敏感文档不出域**
   - 默认不把企业 PDF 上传到外部托管服务
4. **外部服务不是默认主方案**
   - 可以作为研究对象、测试对象或极少量临时备选
   - 但不应成为生产主链路

因此：

- 后续若接 Stirling-PDF，应按**本地部署 PDF 服务**接入
- 后续若接 OCRmyPDF，应按**本地 OCR provider**接入
- 不再把“外部 API 方式”作为默认方案

## 候选项目

### 1. Stirling-PDF

项目：

- https://github.com/Stirling-Tools/stirling-pdf

官方说明要点：

- 支持 50+ PDF 工具
- 可本地部署
- 提供私有 API
- 支持自动化工作流 / pipeline
- 支持 OCR、压缩、转换、编辑、签名、脱敏等

适配判断：

- **功能完整度：高**
- **服务化集成能力：高**
- **Bot 后端化适配度：高**
- **部署复杂度：中**
- **资源要求：中到高**

适合场景：

- 需要把 PDF 能力做成独立后端服务
- 需要 REST API
- 需要批处理和工作流
- 后续希望减少大量 PDF 自研维护工作

### 2. OCRmyPDF

项目：

- https://github.com/ocrmypdf/OCRmyPDF

官方说明要点：

- 专注扫描 PDF OCR
- 支持 100+ 语言
- 可生成可搜索 PDF/A
- 对大批量 OCR 与扫描件场景很成熟

适配判断：

- **OCR 能力：极强**
- **全套 PDF 能力：弱**
- **服务化能力：中**
- **集成复杂度：中**

适合场景：

- 作为“扫描件 OCR 专项能力”
- 不适合作为整个 PDF 能力后端主项目

### 3. PyMuPDF

项目：

- https://github.com/pymupdf/pymupdf

官方说明要点：

- 高性能 PDF 读写与提取
- 支持文本、图片、渲染、转换、修改
- Python 集成非常方便

适配判断：

- **性能：高**
- **Python 集成难度：低**
- **能力覆盖：中高**
- **服务化与企业化：弱于 Stirling-PDF**

适合场景：

- 当前项目内嵌式工具层
- 快速实现自定义 PDF 能力
- 作为内部 provider 的基础库

### 4. pypdf / pikepdf

项目：

- https://github.com/py-pdf/pypdf
- https://github.com/pikepdf/pikepdf

适配判断：

- `pypdf`：纯 Python、简单稳妥，适合轻量合并/拆分/读取
- `pikepdf`：更偏正确性、修复、底层 PDF 操作

适合场景：

- 局部替换工具
- 作为底层补充库
- 不适合作为“完整 PDF 平台”主选型

## 综合结论

如果目标是：

- **给 Bot 提供完整 PDF 后端能力**
- **尽量减少后续大量自研 PDF 功能**
- **保留本地私有化部署**
- **后续还想走 API / pipeline / batch processing**

则最合适的主选项目是：

## 推荐主选：Stirling-PDF（本地私有部署）

### 原因

1. **功能最完整**
   - 它不是单一库，而是成熟的 PDF 平台
   - 对你这个“Bot 调能力”的架构特别合适
2. **天然适合后端化**
   - 提供 API
   - 适合作为企业内网中的独立能力服务
3. **和当前架构契合**
   - 你的系统已经是 `Bot First, Capability Backend`
   - Stirling-PDF 正好可以成为 `files.pdf.*` 的外部 provider
4. **降低后续开发难度**
   - 未来很多 PDF 能力不必继续自研

## 推荐配套：OCRmyPDF（作为本地 OCR 专项补充）

不建议把 OCRmyPDF 作为主 PDF 平台，但建议保留为后续专项补充：

- `files.pdf.ocr`
- 扫描件转可搜索 PDF
- 图片型 PDF 结构化增强

## 当前建议的落地方式

### 短期

- 继续保留当前 internal provider
- 用现有 `PyMuPDF` 工具链支撑基础 PDF 能力

### 中期

- 新增 `stirling_pdf_provider.py`
- 通过**本地服务 API**对接 Stirling-PDF
- 将 `files.pdf.*` 能力逐步切换为：
  - internal provider
  - Stirling provider
  - 双 provider 并存，按能力选择

### 长期

- `OCRmyPDF` 单独挂成 OCR provider
- `files.pdf.ocr` 独立能力域化

### 当前最新进展

项目内已补齐：

- `src/platform/ocrmypdf_provider.py`
- `files.pdf.ocr`
- `builtin:ocr_pdf`

说明：

- OCRmyPDF 不再只是纸面选型
- 已进入统一能力后端的第一版实现

## 对当前项目的明确建议

### 不建议

- 继续把所有 PDF 能力长期都堆在 `pdf_tool.py` 里自研

### 建议

- 当前继续用 internal provider 快速推进
- 下一阶段优先引入 `Stirling-PDF` 作为正式 PDF 服务后端
- OCR 单独考虑 `OCRmyPDF`

## 当前选型结论

| 项目 | 角色 |
|------|------|
| Stirling-PDF | 主 PDF 后端推荐 |
| OCRmyPDF | OCR 专项补充 |
| PyMuPDF | 当前 internal provider 基础库 |
| pypdf / pikepdf | 局部补充，不作为主平台 |

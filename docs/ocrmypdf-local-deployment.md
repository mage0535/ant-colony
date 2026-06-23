# OCRmyPDF 本地部署说明

## 目标

为项目提供一个**本地私有部署**的 OCR 能力后端，专门处理：

- 扫描型 PDF
- 图片型 PDF
- 需要生成可搜索 PDF 的场景

并作为统一能力协议中：

- `files.pdf.ocr`

的默认本地 provider。

## 当前定位

当前项目对 OCR 的定位是：

- `OCRmyPDF` = 本地 OCR provider
- 面向扫描型 PDF 的可搜索化处理
- 与 `internal provider`、`Stirling-PDF provider` 并行演进

## 当前代码落点

- `src/platform/ocrmypdf_provider.py`
- `src/platform/capability_backend.py`
- `src/platform/__init__.py`
- `src/tools/builtin.py`

## 当前能力

已纳入统一能力后端：

- `files.pdf.ocr`

工具入口：

- `builtin:ocr_pdf`

平台包装：

- `src.platform.ocr_pdf()`

## 运行要求

当前实现默认依赖本机可执行文件：

```text
ocrmypdf
```

provider 的可用判断：

- `shutil.which("ocrmypdf")`

## 健康检查

当前 provider 健康检查方式：

```bash
ocrmypdf --version
```

也可以在 Python 中直接调用：

```python
from src.platform.ocrmypdf_provider import OcrmypdfProvider
print(OcrmypdfProvider().healthcheck())
```

## 当前最小验收标准

本地 OCRmyPDF provider 至少应满足：

1. `ocrmypdf --version` 可执行
2. `files.pdf.ocr` 能调用成功
3. 输出 PDF 可被搜索文本

## 后续建议

### 短期

- 保持当前本地命令行 provider 模式
- 继续与 `Stirling-PDF` 和 `internal provider` 并存

### 中期

- 若实际批量 OCR 压力较高，可单独抽为本地 OCR 服务
- 给 OCR 任务增加异步执行与状态追踪

### 长期

- 继续细化：
  - `files.pdf.ocr`
  - `files.pdf.ocr_status`
  - `files.pdf.ocr_batch`

## 不建议的做法

- 不建议将扫描件默认送到外部 OCR SaaS
- 不建议把 OCR 能力写死在单个脚本中，脱离统一能力协议
- 不建议将 OCR 与普通 PDF 读写逻辑混成一个不可替换的大函数

# Stirling-PDF 本地部署说明

## 目标

为项目提供一个**本地私有部署**的 PDF 后端服务，作为 `files.pdf.*` 能力族后续扩展的正式落点。

当前原则：

- 仅作为企业内网服务使用
- 默认仅监听本机回环地址
- 不作为公网托管服务暴露

## 当前配置约定

环境变量：

- `STIRLING_PDF_URL`
  - 默认：`http://127.0.0.1:8080`
- `STIRLING_PDF_API_KEY`
  - 可选
  - 若本地部署启用 API Key，则填入

当前 provider 代码：

- `src/platform/stirling_pdf_provider.py`

当前统一能力探针：

- `files.pdf.service_status`
- `builtin:pdf_service_status`

## Docker Compose 模板

已提供：

- `infra/stirling-pdf.compose.yml`

推荐启动方式：

```bash
cd infra
docker compose -f stirling-pdf.compose.yml up -d
```

## 当前建议的目录

建议在项目根目录下准备：

```text
data/
└── stirling-pdf/
    ├── trainingData/
    ├── extraConfigs/
    └── logs/
```

## 验证步骤

### 1. 服务启动后

本地应可访问：

- `http://127.0.0.1:8080`

### 2. 代码侧探针

当前项目可通过：

- `builtin:pdf_service_status`

检查本地服务状态。

### 3. Python 直接检查

```python
from src.platform.stirling_pdf_provider import StirlingPdfProvider
print(StirlingPdfProvider().healthcheck())
```

## 当前阶段定位

当前 `Stirling-PDF` 还属于：

- **本地部署骨架已就绪**
- **服务状态探针已接入**
- **实际 PDF 能力调用待后续逐步补齐**

已完成的阶段：

1. 私有部署原则固化
2. provider 骨架
3. service status 能力

后续计划：

1. `files.pdf.merge` 等能力逐步支持 Stirling provider
2. provider 选择策略从“internal 优先”演进为“stirling 优先、internal 兜底”
3. `files.pdf.ocr` 与 OCRmyPDF 结合

## 不建议的做法

- 不建议把 Stirling-PDF 直接暴露公网
- 不建议把企业敏感 PDF 默认送到第三方托管 API
- 不建议跳过本地健康探针直接接业务调用

# ETF 对比分析助手

> 搜索 ETF 名称或代码，一键添加对比标的。Agent 并行查询基本面、实时行情、历史业绩，生成结构化对比报告。
>
> 与 [ETF 持仓解释工具](https://github.com/djk2026/etf-holdings) 互补——前者"看懂持仓"，本项目"对比选哪只"。

---

## 为什么用 Agent

单次 LLM 调用无法同时查询多只 ETF 的多维度数据。Dify Workflow Agent 的并行 Tool 节点是天然解法：

- **3 个 Tool 并行调用**：基本信息 / 实时行情 / 历史业绩同时获取，不串行等待
- **LLM 只负责推理**：数据聚合清洗由 Code 节点完成，LLM 专注生成对比报告
- **结构化约束**：System Prompt 强制表格 + 逐只解读 + 维度总结格式

## 功能特性

- **模糊搜索 + 标签选择**：输入"沪深300"即可搜出所有跟踪沪深 300 指数的 ETF，点击标签添加对比，无需记忆代码
- **键盘导航支持**：↑↓ 选择、Enter 确认、Esc 关闭、Backspace 删除标签
- **3 维度并行对比**：基本信息（规模/费率/跟踪指数/跟踪误差）、实时行情（最新价/涨跌幅/成交额）、历史业绩（1周/1月/3月/6月/1年）
- **AI 解读报告**：多 ETF 模式下输出对比总览表格 + 逐只解读 + 维度对比总结；单 ETF 模式下用表格呈现完整档案（基本画像/费率与跟踪/收益表现）+ 潜在关注点
- **数据标注**：缺失数据标注"暂无数据"，底部标明数据延迟 15-30 分钟

---

## 架构

```mermaid
flowchart LR
    A[用户浏览器] --> B[Vercel 前端<br/>Vue3 CDN + marked.js]
    B --> C[Vercel Serverless<br/>API Key 代理]
    C --> D[Dify Cloud<br/>Workflow Agent]
    D --> E1[Tool: ETF 基本信息]
    D --> E2[Tool: 实时行情]
    D --> E3[Tool: 历史业绩]
    E1 & E2 & E3 --> F[Vercel 数据服务<br/>Python Serverless]
    F --> G1[东方财富<br/>fund.eastmoney.com<br/>fundf10 tsdata]
    F --> G2[新浪财经<br/>hq.sinajs.cn]
```

| 层 | 技术 | 部署 | 说明 |
|---|------|------|------|
| 前端 | Vue 3 CDN + marked.js | Vercel Static | 单文件 `index.html`，零构建 |
| API 代理 | Node.js Serverless | Vercel Functions | 隐藏 Dify API Key |
| Agent 编排 | Dify Workflow | Dify Cloud | 6 节点：开始→清洗→3Tool并行→聚合→LLM→结束 |
| 数据服务 | Python Serverless | Vercel Functions | 3 个端点，零依赖（仅 `urllib`） |
| 数据源 | 新浪财经 / 东方财富 | 公开接口 | GBK 编码，需 Referer |

---

## 快速体验

| 方式 | 链接 |
|------|------|
| **网页版** | [https://etf-compare-agent-jba2.vercel.app](https://etf-compare-agent-jba2.vercel.app) |
| **数据服务 API** | `https://etf-compare-agent-jba2.vercel.app/api/etf/` |

**使用方式**：在搜索框输入 ETF 名称（如"沪深300"）或代码（如"510300"），从下拉列表中点击添加，选好 2-5 只后点击"开始对比"，等待约 10-20 秒即可看到完整的 AI 对比报告。

也可直接使用快捷标签：`沪深300 + 创业板` 一键填入两组对比候选。

---

## 项目结构

```
etf-compare-agent/
├── index.html                  # 前端：Vue3 CDN + marked.js 单文件
│                                #   - 模糊搜索 + 标签选择 + 键盘导航
│                                #   - 快捷示例标签 + Loading 动画
│                                #   - Markdown 报告渲染
├── api/
│   ├── compare.js              # Vercel Serverless：Dify API Key 代理
│   └── etf/
│       ├── _shared.py          # 共享：东方财富/新浪抓取逻辑
│       ├── basic.py            # → /api/etf/basic
│       ├── snapshot.py         # → /api/etf/snapshot
│       ├── performance.py      # → /api/etf/performance（并发K线）
│       └── search.py           # → /api/etf/search（模糊搜索）
├── data-service/               # 本地开发用 FastAPI（保留）
│   ├── main.py
│   ├── shared.py
│   └── requirements.txt
├── dify/
│   └── workflow-dsl.yml        # Dify Workflow 可导入文件
├── PROJECT_MANUAL.md           # 完整项目手册（需求/架构/Prompt/踩坑）
├── IMPLEMENTATION_PLAN.md      # 实施计划（20 步可验收）
└── .gitignore
```

---

## Dify Workflow 拓扑

```
开始(用户输入codes)
  → Code节点#1: 清洗+校验(去空格/去重/限5只)
  → 3个HTTP节点并行:
      ├── POST /api/etf/basic      (东方财富基金列表)
      ├── POST /api/etf/snapshot   (新浪实时行情)
      └── POST /api/etf/performance (新浪K线计算)
  → Code节点#2: 数据聚合+构建对比矩阵
  → LLM节点(DeepSeek-V4): 生成结构化报告
  → 结束
```

---

## 数据服务 API

| 端点 | 方法 | Body | 数据 | 数据源 |
|------|------|------|------|--------|
| `/api/etf/search` | GET | `?keyword=科创` | ETF 搜索建议（代码/名称/公司） | 东方财富 `fundcode_search.js` |
| `/api/etf/basic` | POST | `{"codes":["510300"]}` | 名称、规模、费率、跟踪指数、跟踪误差、行业分类 | 东方财富 `fundcode_search.js` + tsdata 页面 |
| `/api/etf/snapshot` | POST | `{"codes":["510300"]}` | 最新价、涨跌幅、成交额 | 新浪 `hq.sinajs.cn`（HTTP） |
| `/api/etf/performance` | POST | `{"codes":["510300"]}` | 1周/1月/3月/6月/1年涨跌幅、跟踪误差 | 新浪 K 线 + 东方财富 tsdata |

---

## 技术选型

| 技术 | 选型 | 理由 |
|------|------|------|
| Agent 编排 | Dify Cloud | 免费层足够，可视化 Workflow，适合演示 |
| LLM | DeepSeek-V4 | 性价比高，中文能力强 |
| 数据服务 | Python (urllib) | 零依赖，Vercel Serverless 原生支持 |
| 前端 | Vue 3 CDN + marked.js | 单文件，零构建，部署即用 |
| 部署 | Vercel | 免费，免信用卡，Git push 自动部署 |

---

## 本地开发

```bash
# 数据服务（FastAPI 版，端口 8001，避免与 ETF 持仓工具冲突）
cd data-service
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
# 访问 http://localhost:8001/docs 查看 Swagger

# Vercel 版（本地模拟）
npm i -g vercel
vercel dev
```

---

## 部署

```bash
# 1. 推送到 GitHub
git push

# 2. Vercel 自动部署
# 3. 设置环境变量：DIFY_API_KEY = app-xxxxxxxxxxxxxx
# 4. Dify 导入 DSL：dify/workflow-dsl.yml
```

### 重建 Dify Workflow

1. 注册 [cloud.dify.ai](https://cloud.dify.ai) → 创建空白 Workflow
2. 右上角 ... → 导入 DSL → 选择 `dify/workflow-dsl.yml`
3. 3 个 HTTP 节点 URL 改为你自己的 Vercel 域名
4. 发布即可

---

## 行为准则（LLM System Prompt 约束）

1. 禁止投资建议（不说"推荐买入""建议持有"）
2. 禁止编造数据（缺失标注"暂无数据"）
3. 白话翻译专业术语
4. 底部标注数据延迟 15-30 分钟
5. 结构化输出：多 ETF → 对比表格 + 逐只解读 + 维度对比总结；单 ETF → 表格档案（基本画像/费率与跟踪/收益表现）+ 潜在关注点
6. 最多对比 5 只

---

## 许可

MIT License

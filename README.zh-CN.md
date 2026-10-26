# ProofPress

**一条给 AI agent 用、带事实核查的 SEO 文章流水线。** 你在设置页里填好产品信息、导入关键词，你的 agent（Claude Code、Codex、Cursor、Claude Desktop……）每次写一篇，文章必须过几道闸门才会发布：

- **产品真实性：** 只能写产品定义里列出的功能。没列出的一律当作不存在，编不出功能、价格和平台。
- **当场核实：** 你标记为敏感的说法（税务、健康、法律、竞品价格）必须在写作当下对照认可的来源核实，核实不了就删掉。
- **去 AI 味：** 机械扫描器加两轮人工通读，清掉夸张词、空话、假钩子和机械节奏。
- **独立打分：** 由一个没参与写作的评审按 100 分制打分。低于及格线就重写，超过最大重写次数就交还给你，不会自动上线。

通过之后，ProofPress 生成封面图并发布。可以生成一个完整的静态站（首页、博客列表、sitemap、结构化数据、内链），部署到 S3、Cloudflare Pages、Netlify、Vercel 或任何连着 git 的托管平台；也可以直接写进你已有的网站（Astro/Hugo/Next 的 Markdown 仓库、WordPress，或任意 webhook）。

整个项目是一个文件夹：一个不依赖第三方库的 Python 引擎、一个本地设置页、一个 Claude skill 和一个 MCP server。

![设置页：产品定义](docs/images/settings-product.png)

![设置页：关键词库](docs/images/settings-keywords.png)

![生成的文章页面](docs/images/article.png)

```
proofpress/
├── cli/proofpress            命令行（不用安装）
├── cli/proofpress-mcp        MCP server 启动脚本
├── proofpress/               引擎 + 设置页（Python 3.9+，只用标准库）
├── skills/proofpress/        agent skill：流水线 + 参考手册
├── mcp/server.py             MCP server（stdio）
├── .claude-plugin/           Claude Code 插件（skill + MCP server）+ marketplace 清单
├── examples/demo-project/    一个填好的虚构示例项目，可以直接构建
└── docs/                     部署指南
```

## 快速上手（5 分钟）

```bash
git clone https://github.com/BenHugh/proofpress.git
cd proofpress
./install.sh                      # 把 CLI 加到 PATH、装 markdown + pillow、给 Claude Code 装 skill 和 MCP
source ~/.zshrc                   # 或者新开一个终端窗口，这样才能找到 proofpress 命令

# 先跑示例：构建虚构的 "Leafnote" 站点并打开看看
proofpress build --project examples/demo-project
python3 -m http.server 8000 --directory examples/demo-project/public   # 打开 http://localhost:8000

# 建你自己的项目
proofpress init ~/sites/my-product --name "My Product"
proofpress ui --project ~/sites/my-product
```

`proofpress ui` 会在浏览器里打开设置页（右上角可切换中英文）。填完各页点保存，“总览”页会告诉你还缺什么。

然后在 Claude Code 里说：

> 用 proofpress 给 ~/sites/my-product 写下一篇文章

## 设置页

所有和项目相关的东西都在这里填，不会写死在代码里：

| 页面 | 填什么 | 生成 |
|---|---|---|
| 站点与品牌 | 名称、网址、语言、博客路径、颜色、CTA 按钮 | `proofpress.json` |
| 产品定义 | 一句话介绍、目标用户、官方链接、价格的唯一说法、**功能及套餐/平台限制**、**不存在的功能**、定位、利益披露、措辞规则 | `context/product.md` |
| 关键词库 | 逐行添加、粘贴或上传 CSV（页面上有格式说明）、筛选、下载 | `backlog.csv` |
| 读者与文风 | 读者、语气、要/不要、示范段落 | `context/voice.md` |
| 事实核查 | YMYL 开关、必须核实的说法、认可来源、额外规则、免责声明 | `context/factcheck.md` |
| 发布方式 | 新静态站 + 托管平台，或已有网站 + 目标；测试按钮（构建、dry run、发布） | `proofpress.json` |
| 质量闸门 | 及格线、最多重写次数、额外禁用词 | `proofpress.json` |

设置页只在 `127.0.0.1` 上运行，每次启动有独立 token。密钥（API token、密码）**永远不会**保存，只读环境变量。

更喜欢直接改文件？`proofpress.json` 和 `backlog.csv` 都是普通文件；在某个 context 部分勾选“手动模式”，就可以直接手改对应的 Markdown。

### 关键词 CSV 格式

```csv
keyword,cluster,priority,intent_hint,status,slug,published_at,notes
best plant watering app,apps,1,buying guide,todo,,,"secondaries: plant care app"
plant watering schedule template,schedules,1,list (download),todo,,,
```

只有 `keyword` 必填。`priority` 是 1 到 3（1 最先写）。`intent_hint` 可选：buying guide、comparison、how-to、definition、troubleshooting、list、list (download)。`status`：todo、drafting、approved、published、blocked、skip。同一个 `cluster` 的多行会合并成一篇文章。

## 在 agent 里使用

### Claude Code（插件）

```bash
claude plugin marketplace add BenHugh/proofpress
claude plugin install proofpress@proofpress
```

一次装好 skill 和 MCP server。也可以在克隆下来的目录里运行 `./install.sh --skill --mcp`。

### 任何 MCP 客户端（Claude Desktop、Cursor、Windsurf、Codex……）

```json
{
  "mcpServers": {
    "proofpress": {
      "command": "python3",
      "args": ["/绝对路径/proofpress/mcp/server.py"],
      "env": { "PROOFPRESS_PROJECT": "/绝对路径/你的项目" }
    }
  }
}
```

server 的 `get_instructions` 工具会返回完整的操作手册，所以不支持 skill 的客户端也会按同样的流水线走。

### 其他 agent（只用 skill）

把 `skills/proofpress/` 复制到你的 agent 加载 skill 的目录（Claude Code 是 `~/.claude/skills/`）。skill 会调用 `proofpress` 命令行，所以也要把 `cli/` 加到 PATH（`./install.sh --cli`）。

## 发布目标

**新静态站**：S3 + CloudFront（AWS CLI profile，一次性配置见 [docs/deploy.md](docs/deploy.md)）、Cloudflare Pages（`CLOUDFLARE_API_TOKEN`）、Netlify（`NETLIFY_AUTH_TOKEN`）、Vercel（`VERCEL_TOKEN`）、Git 仓库（推送后由托管平台自动部署）、或者只构建（自己上传 `public/`）。

**已有网站**：Markdown 仓库（按 Astro / Hugo / 原样 frontmatter 写入、复制封面图、提交，可选推送）、WordPress（REST API 创建或更新文章，默认存草稿，需要 `WP_APP_PASSWORD` 应用密码）、Webhook（POST 包含 markdown、html、frontmatter、JSON-LD 和封面图的 JSON）。

建议每次先点 **Dry run**：只打印将要执行的命令或请求，不会上传任何东西。

## 环境要求

- Python 3.9+（macOS 和大多数 Linux 自带）
- 可选：`markdown`（生成 HTML、WordPress、webhook）和 `pillow`（封面图）：`pip install -r requirements.txt`
- 只有 Cloudflare / Netlify / Vercel 直接上传需要 Node.js
- 一个能联网搜索的 agent，用来看搜索结果页和做当场核实

## 它不会做的事

不会自己选题，不会添加你没批准的关键词，不会发布没过闸门的草稿，也不会保存你的密钥。它不保证排名：它保证每篇文章诚实、具体、有用，这是你能控制的那部分。

## 许可

[Functional Source License 1.1（Apache 2.0 未来许可）](LICENSE)，即 FSL-1.1-ALv2，和 Typebot、Sentry 用的是同一类许可证。它属于 Fair Source（公平源码），不是 OSI 定义的开源：

- **允许：** 给自己或公司的网站使用、修改、分享、教学，以及用它给客户做 SEO 服务。
- **不允许：** 把它（或基于它做出的实质相同的东西）做成竞争性的商业产品或托管服务。
- **每个版本发布满两年后**，自动变成没有限制的 Apache 2.0。

用 ProofPress 写出来的文章归你所有。

[English](README.md)

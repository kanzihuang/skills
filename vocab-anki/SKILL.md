---
name: vocab-anki
description: >
  Generate Anki vocabulary flashcard decks from WeRead (微信读书)
  English book highlights. Syncs directly to Anki via AnkiConnect plugin.
  Use when user wants to create Anki cards from WeRead highlights, e.g.
  "/vocab-anki The Little Prince" or "为这本书的划线生词生成 Anki 牌组".
  Also supports full-text mode: extract vocabulary from entire book text
  with COCA frequency range and chapter range filtering.
  Integrates with weread-skills for data; Claude does knowledge work
  (sentences, translations), Python scripts handle audio + sync.
---

# vocab-anki — 英文书词汇 Anki 牌组生成

将微信读书英文原版书的划线生词（或全书词汇）通过 AnkiConnect 直接同步到 Anki，嵌入发音音频。
自动对比已有卡片，仅添加新词，保留学习进度不受影响。

## 两种模式

| 模式 | 输入 | 触发词 | 适用场景 |
|------|------|--------|----------|
| **划线模式**（默认） | 微信读书划线 | "/vocab-anki 书名"、"划线生词" | 从已读划线的生词制作卡片 |
| **全文模式** | 图书原文 | "全文制作"、"全量词汇"、"按 COCA 词频"、"词频范围"、"指定章节"、"全文" | 按词频/章节范围从全书提取词汇 |

全文模式额外支持：
- **COCA 词频范围**：自然语言描述（如 "COCA 3000-10000"、"排除前3000高频词"），不明确时提问确认
- **章节范围**：先展示检测到的章节列表，用户选择（如 `1-5,7,10-12`）
- **Anki 去重范围**：必须提问确认——仅排除同本书已有卡片，还是排除本技能制作的所有牌组中的单词

## 前置条件

- `weread-skills` 已安装，`WEREAD_API_KEY` 环境变量已设置
- Python 3 + venv（脚本会自动创建 venv 并安装依赖）
- Anki 正在运行 + [AnkiConnect 插件](https://ankiweb.net/shared/info/2055492159) 已安装

> **云主机/远程环境**：若 Claude Code 运行在远程主机而 Anki 在本地，需通过 SSH 反向隧道转发 AnkiConnect 端口：
> ```bash
> ssh -R 8765:localhost:8765 user@remote-host
> ```
> 转发后，远程主机的 `localhost:8765` 即指向本地 AnkiConnect。连接不稳定时可加 `-o ServerAliveInterval=60` 保持隧道活跃。

## 工作流

> **核心原则：每次执行都必须重新从微信读书获取最新划线。禁止依赖缓存的 JSON 或之前的运行结果，因为用户可能在此期间添加了新的划线。**
>
> **确认策略：整个流程仅在 Step 4（音频已预下载、同步/导出前）进行一次用户确认。其他步骤（含 Step 3.5 音频预下载）仅输出进度，不询问。**

### Step 0: 前置检查（含 Anki 牌组 bookId 桥接）

在开始任何 API 调用之前，先检查环境并建立 Anki ↔ 微信读书的 bookId 桥接。

**0a. 检查环境变量：**

```bash
[ -n "$WEREAD_API_KEY" ] || echo "MISSING"
```

若未设置 → 提示 `export WEREAD_API_KEY=<你的 key>`，终止。

**0b. 检查 AnkiConnect 可达性并建立 bookId 映射（并行两次 curl）：**

```bash
# 并行：牌组列表 + Vocabulary Card (WeRead) 笔记总数
curl -s http://localhost:8765 -d '{"action":"deckNamesAndIds","version":6}' &
curl -s http://localhost:8765 -d '{"action":"findNotes","version":6,"params":{"query":"note:\"Vocabulary Card (WeRead)\""}}' &
wait
```

若 AnkiConnect 可达：
- **全库 0 张 "Vocabulary Card (WeRead)" 笔记** → Step 1e 直接得 A=0，**不查 Anki**。
- 若有卡片 → 查普通单词卡片：`WordId` 格式 `{lemma}_{bookId}`，从 `_{bookId}` 后缀解析出 `bookId`，形成映射表：

```
{牌组名: bookId}
```

**目的**：用 bookId 作为 Anki ↔ 微信读书的精确桥接。每张卡片的 WordId 天然包含 bookId，无需额外存储。

> **⚠️ Anki 搜索引号规则**：牌组名含 `()`、空格等特殊字符时，Anki 会误解析为分组/分隔符，必须用双引号包裹：`deck:"牌组名"`。

### Step 1: 获取划线（智能路由）

通过 weread API gateway 获取划线：

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Content-Type: application/json
```

**1a. 路由判断：**

- **若 Step 0 匹配到已有牌组**（用户说的书名对应某个牌组名）：
  - 从牌组卡片 WordId 解析出 `bookId` → 直接用 bookId 调用 `/book/bookmarklist` 和 `/book/info`
  - **跳过 `/store/search`**——不需要搜索
  - `book_title` 和 `book_author` 从牌组名 `"{title} ({author})"` 解析，确保与 Anki 一致

- **若未匹配到**（新书，尚无牌组）：
  - **先查书架**：调 `/shelf/sync` 获取用户已加入书架的所有书籍，按书名匹配（支持中英文模糊匹配）。书架命中 → 直接用 bookId 调用 `/book/bookmarklist` 和 `/book/info`，跳过搜索
  - 书架未命中时走搜索：`/store/search` → 选书 → `/book/info` → `/book/bookmarklist`
    - **搜索关键词优先用中文书名**：微信读书搜索 API 对英文标题支持差（常见返回空结果），中文书名搜索命中率远高于英文
  - 多版本时，并行检查英文版划线数量，标出划线最多的版本
  - `book_title` 和 `book_author` 用微信读书 API 返回值

**1b. 获取书籍信息：**

```json
{"api_name": "/book/info", "bookId": "<bookId>", "skill_version": "1.0.3"}
```

**1c. 获取划线内容：**

```json
{"api_name": "/book/bookmarklist", "bookId": "<bookId>", "skill_version": "1.0.3"}
```

`updated[]` 数组含 `markText`、`chapterUid`、`createTime`；`chapters[]` 含章节标题。

> **Claude 注意**：若 Step 1d 输出 `SUMMARY: 0 highlights → 0 lemmas`，在判定"没有划线"之前先用 `head -c 500` 查看原始 API 响应，确认 `updated` 字段确实存在且为空数组，排除 API 调用失败（如 `$WEREAD_API_KEY` 拼写错误导致认证失败）。

**1d. 筛选 + 原形去重 + Anki 去重 + COCA 批量检查（单次 Python 流水线，不询问用户）：**

> 合并原 Steps 1d/1e/1f 为一次 `filter_pipeline.py` 调用。脚本内部按序执行：
> 原形提取 → Anki 去重 → COCA 检查。
> **禁止 Claude 在 echo 中传递数据**——所有数据通过 stdin/stdout 在进程间流通。

```bash
# 确保 venv 存在（仅首次）
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 提取划线 → 原形去重 → Anki 去重 → COCA 检查（单次调用）
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/book/bookmarklist","bookId":"<bookId>","skill_version":"1.0.3"}' | \
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_pipeline.py --anki-dedup same-book --book-id <bookId> --json-out /tmp/vocab-anki-filtered-<bookId>.json
```

- `--anki-dedup same-book`：启用同书 Anki 去重（查已有卡片）；若 Step 0b 确认全库 0 张 Vocabulary Card 笔记，可省略此 flag 跳过 Anki 查询
- `--book-id <bookId>`：bookId 标识，用于 WordId 构建 + 同书去重目标
- `--json-out <path>`：将过滤结果写入结构化 JSON 文件，供 Step 3 Claude 直接读取填充 `excluded` 数组，避免手动转录

输出分为四段：`SUMMARY:` 行、`---IN_COCA---` 表、`---EXCLUDED---` 表、`---ANKI_SKIPPED---` 表（Anki 已有卡片，仅当存在时出现）。同时写入对应的结构化 JSON 到 `--json-out` 路径。

JSON 输出中 `in_coca[]` 每项含 `chapters` 字段：
```json
{
  "lemma": "abruptly",
  "rep": "abruptly",
  "forms": ["abruptly", "abruptly"],
  "chapters": [
    {"chapterUid": 96, "chapterTitle": "Chapter 3"},
    {"chapterUid": 98, "chapterTitle": "Chapter 5"}
  ]
}
```
- `chapters`：该词所有出现的章节列表（按 `chapterUid` 升序）；词在多个章节被划线时含多个条目
- `chapterUid` 为 WeRead 内部章节 ID，`chapterTitle` 为章节标题（如 "Chapter 10"）
- Step 3.0 用此信息在源文本中定位章节范围，优先在该范围内搜索句子

> **Claude 注意**：若输出 `SUMMARY: 0 highlights → 0 lemmas`，在判定"没有划线"之前先用 `head -c 500` 查看原始 API 响应，确认 `updated` 字段确实存在且为空数组，排除 API 调用失败。

**Step 1 汇总（仅数字，不确认）：**

> 一步完成，中间不暂停、不询问用户。

```
划线 X 条 → 原形去重 Y 个 → Anki 已有 A 个, 历史排除 M 个 → 新增 COCA 排除 B 个 → 待生成内容 C 个
```

> Anki 去重先于 COCA：已在牌组中的词直接保留，不受 COCA 频次影响。COCA 仅对真正的新词做筛。所有检查均为本地/本地网络查询（~0.5s），无需缓存。

---

## 全文模式工作流

> 当用户使用以下关键词时，跳过划线模式 Step 1，走以下全文模式分支：
> **"全文制作"、"全量词汇"、"全文"、"按 COCA 词频"、"词频范围"、"指定章节"、"排除前X高频词"、"COCA X-Y"、"COCA X到Y"、"全部生词"**
>
> 仅含 "生成牌组"、"制作卡片"、"Anki" 等词而不含上述关键词 → 走划线模式。
> 全文模式的其他步骤（Step 3.0、Step 3、Step 3.5、Step 4）与划线模式相同。

### Step 1-FT.0: 需求确认

在获取数据前，确认用户未明确表述的需求：

| 参数 | 默认 | 何时提问 |
|------|------|---------|
| COCA 词频范围 | 无限制（全部 COCA 20000） | 用户未指定范围，或表述模糊（如 "中频词"） |
| 章节范围 | 全部章节 | 用户未指定，或表述模糊 |
| Anki 去重范围 | **必须提问确认** | 用户未明确说明时显式提问；提及 "所有牌组"/"全局" → `--anki-dedup all-decks`；提及 "仅本书"/"同书" → `--anki-dedup same-book` |

**COCA 范围意图解析：**

| 用户表达 | 解析结果 | `--basic-range` |
|----------|---------|-----------------|
| "COCA 3000-10000" | 排名 3001-10000 | `3001-10000` |
| "排除前3000高频词" / "排除前3000" | 排除 top 3000 | `3001-18964` |
| "5000以内" / "前5000" | 排名 1-5000 | `1-5000` |
| "中频词" / "中等难度" | 大致 3001-8000 | **提问确认具体范围** |
| "全部COCA词" / 未提及 | 无范围限制 | 省略 `--basic-range` |

> 1-based rank: rank 1 = 最高频词 ("the")。范围两端均 inclusive。

### Step 1-FT.1: 获取数据（并行两步）

**与划线模式共享 Step 0、Step 1a-1b**（bookId 桥接、搜索/路由、bookInfo）。

并行执行：

**(a) 获取 WeRead 章节列表：**

```json
{"api_name": "/book/chapterinfo", "bookId": "<bookId>", "skill_version": "1.0.3"}
```

目的：获取完整章节层级。返回的 `chapters[]` 含 `level` 字段——level=1 是封面/版权/书名页等元数据，level=2 是实际内容章节。`updated[]` 划线数据在全文模式不使用。

> **注意**：`/book/bookmarklist` 的 `chapters[]` 仅返回 level-1 章节，会漏掉嵌套的实际内容章节。**全文模式必须用 `/book/chapterinfo`**。

**(b) 获取全文：**

与 Step 3.0a-3.0b 相同：WebSearch → curl 下载 → 验证（`head -c 500` 确认是书的内容，文件 >20KB）。

```bash
curl -sL --max-time 60 '<URL>' -o /tmp/<safe_title>-full.txt
```

> 全文下载在此步骤完成，后续 Step 3.0 即可直接使用，无需重复获取。

### Step 1-FT.2: 章节展示 + 用户选择

从 `/book/chapterinfo` 响应 `chapters[]` 中**过滤 level=2 的章节**（实际内容章节，排除封面/版权/书名页等 level=1 元数据），按原始顺序扁平编号（1-based）：

```
检测到 6 个章节:
  1. 一
  2. 二
  ...
  6. 六

请输入需要制作的章节范围（如 1-3,5），或回车选择全部章节：
```

**用户输入解析规则：**
- 空白 / "全部" / "all" → 全选
- `1-5,7,10-12` → 章节 1-5、7、10-12
- 章节标题关键词匹配（如 "一"、"Chapter 1"）→ 包含即选中

验证：范围在 [1, N] 内，不包含倒置范围（如 10-5）。

如果无 level=2 章节（如短篇无分章），跳过此步，直接处理全文。

> 简短书籍（≤5 章）且用户未指定章节范围时，跳过确认直接处理全部章节。

### Step 1-FT.3: 运行 filter_fulltext.py

```bash
# 确保 venv 存在（仅首次）
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 提取 + 过滤全文词汇
cat /tmp/<safe_title>-full.txt | \
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_fulltext.py \
  --basic-range 3001-10000 \
  --chapter-range "1-5,7,10-12" \
  --chapter-titles '<chapters_json>' \
  --anki-dedup same-book --book-id <bookId> \
  --json-out /tmp/vocab-anki-filtered-<bookId>.json
```

**flags：**
- `--basic-range M-N`：COCA 频率排名范围。省略表示不限制。
- `--chapter-range RANGE`：用户选择的章节。省略表示全部。
- `--chapter-titles JSON`：WeRead API `/book/chapterinfo` 返回的 `chapters[]` 中 **level=2 的章节**序列化为 JSON 字符串（注意 shell 转义）。
- `--anki-dedup same-book|all-decks`：Anki 去重模式。`same-book` 仅同书去重（需 `--book-id`），`all-decks` 全库去重。省略表示不去重。
- `--book-id <bookId>`：用于 WordId 构建 + 同书去重目标
- `--json-out <path>`：输出结构化 JSON。

**脚本内流水线：**
1. 分词：`re.findall(r"[a-zA-Z]{2,}", text)`
2. 章节切分：在原文中搜索 WeRead 章节标题（精确 → 忽略大小写 → 去标点），按字节偏移构建区间
3. 词形还原：spaCy 全文 parse → `{surface→lemma}` 映射（POS-aware，正确处理不规则动词、比较级、派生形容词），fallback `lib.lemmatize.lemmatize()`（lemminflect VERB+NOUN）
4. COCA 范围过滤：`in_coca()` 含派生还原（如 `indulgently` → `indulgent`）+ 频率排名范围
5. Anki 去重：同书（或全库）已有卡片
6. JSON 输出：格式与划线模式 `filter_pipeline.py` 输出一致

### Step 1-FT.4: 汇总展示

```
全文模式分析完成:
- 全文总词例 (tokens): 48,523
- 去重后原形 (lemmas): 3,210
- Anki 已有: 0 个
- COCA 范围外: 2,429 个
- 待生成卡片: 781 个
```

从 stdout `SUMMARY:` 行和 JSON `summary` 字段提取数字展示。**不在此步确认**——继续执行 Step 3.0。

### Step 3.0: 句子匹配（全文模式调整）

全文已在 Step 1-FT.1 下载（`/tmp/<safe_title>-full.txt`），**跳过 3.0a 和 3.0b**，直接从 3.0c 开始。

其余步骤与划线模式完全相同：
- 3.0c 机械匹配句子（章节优先，利用 JSON 中 `in_coca[].chapters` 字段）
- 3.0c-1 验证表面形式确实在句子中
- 3.0c-2 句子完整性检查
- 3.0d 版本验证（查一句名言）
- 3.0e 截断处理（>150 字符）

> **全文模式特有**：每个 lemma 的 `forms` 数组列出了文本中出现的所有表面形式（如 `["abandoned", "abandoning"]`）。匹配句子时，在对应章节的文本中搜索任一形式。`word` 字段填匹配到的表面形式，`lemma` 填原形。

> 若全书文本无法获取（Step 1-FT.1 下载失败）→ 跳过整个 batch，不生成卡片。

---

### Step 3.0: 获取源文本（句子检索替代回忆）

> **核心改进**：回忆式例句生成不可靠——即使对知名书，具体到每个词在哪个句子里也常出错。改为从网上拉取书中实际文本，机械匹配每个生词所在句子，**彻底消除编造风险**。

**3.0a. 搜索源文本：**

WebSearch `<英文书名> full text` 或 `<英文书名> <作者> full text`。优先选 Internet Archive（`archive.org` 的原始文本链接）、Project Gutenberg、Standard Ebooks 等公版书站点。**搜索时重点留意可直链下载的纯文本 URL**（以 `.txt` 结尾或 `/download/` 路径），供下一步 curl 使用。

**3.0b. 拉取源文本（优先 curl 直链，WebFetch 仅作兜底）：**

> **WebFetch 有严格引用字数限制（~125 字符/条），不适合拉取全书文本。必须优先用 `curl -sL` 直接下载。**

```bash
# 优先方案：curl 直链下载纯文本文件
curl -sL --max-time 60 '<3.0a 找到的原始文本 URL>' -o /tmp/<book>-full.txt
# 检查文件大小：公版书通常在 50KB~500KB
wc -c /tmp/<book>-full.txt
```

- **curl 成功**（文件 >20KB 且包含书中文本）→ 直接用，跳过 WebFetch
- **curl 返回 HTML 包装页**而非纯文本 → 试 Internet Archive 的 `/download/` 路径或换其他源
  - Internet Archive 的 `/stream/` URL 常返回 HTML，改为 `/download/` 路径通常可拿到原始文件
  - 例：`https://archive.org/stream/xxx/xxx_djvu.txt` → 试 `https://archive.org/download/xxx/xxx_djvu.txt`
- **所有直链均失败** → 回退 WebFetch 逐章拉取（按章节密度降序，每章单独 WebFetch）
- **章节感知拉取**：对于超长书（>500KB），若源文本支持按章节 URL 访问（如 `.../chapter01.htm`），可直接按单词所在章节列表拉取对应章节，跳过无关章节

**curl 拿到的文本验证**：`head -c 500` 确认是书中实际文本而非 HTML/JS，搜一句知名台词确认版本。（若来源为 Internet Archive，文件头可能有少量元数据说明文字，属正常现象。）

**3.0c. 句子匹配（替换回忆）：**

对每个待生成单词，在源文本中搜索该词（大小写不敏感）→ 提取所在完整句子。

- **章节优先匹配**：从 `filter_pipeline.py --json-out` 输出的 `in_coca[].chapters` 获取该词所属章节及标题。在源文本中定位该章节范围（按章节标题或特征标志文本匹配），**优先在章节范围内搜索**，避免同名异义词匹配到错误章节
- **匹配到** → 该句即为 `sentence` 字段内容，用 `<b>` 包裹目标词
- **未匹配到**（源文本不全/翻译版本不同）→ 仅该词回退到回忆模式，标记 `⚠️`
- **章节边界不确定时**（如源文本无明确章节标记）→ 全文本搜索，仍以匹配到的第一句为准

**3.0c-1. 句子匹配校验（必做）：**

匹配到句子后，**必须逐词确认**：
- 目标词的表面词形（如 `blundering`、`conceited`）实际出现在匹配到的句子中（大小写不敏感）
- 若句中找不到 → 扩大搜索范围到相邻段落；仍找不到 → 标记 `⚠️ 未匹配`，回退到回忆模式
- **绝不**在未确认的情况下将 `word` 字段设为句中不存在的词形

**3.0c-2. 句子完整性检查（必做）：**

提取到的句子必须是**语法完整的句子**（有主语 + 定式动词谓语），不能是名词短语片段。

- **大写首字母检查**：去掉 `<b>` 标签后，首字符必须是大写字母或引号（对话标记）。首字符为小写（如 `the lights…`）→ 强烈信号：从句中截断 → **必须**向前扩展到最近的句首标记（大写字母/句号后的首词）
- **主谓结构检查**：句子必须有可识别的主语 + 定式动词（不是分词/不定式）。纯名词短语如 `the tenderness of smiling faces…` 缺少谓语，不可接受 → 往回扩展直到找到主句的主谓结构
- **禁止**在未确认完整性的情况下将片段写入 `sentence` 字段
- **对话例外**：对话句中 `"…"` 内部首字母可能不遵循常规大写规则，此时以引号边界作为句子边界

**3.0c-3. 扩展策略：**

若初始匹配是片段 → **向外扩展**到完整句子边界：
- **向前**：找到最近的句号/问号/感叹号 → 取其后的第一个大写字母作为句首
- **向后**：找到最近的句号/问号/感叹号 → 以该标点作为句尾
- 若扩展后仍 >150 字符 → 交由 3.0e 截断规则处理

**3.0d. 版本校验（1 次快速检查）：**

源文本中搜一句书中知名台词（如《小王子》搜 `wasted for your rose`）：
- 匹配到 → 版本一致
- 未匹配 → 版本可能不同，但仍以源文本句子为准（比回忆可靠）

**3.0e. 截断长句（必须产出完整句子）：**

若完整句子 >150 字符 → 截断，但**截断后必须仍是语法完整的句子**。

**截断目标**：≤150 字符、语法完整、含生词上下文的句子。

**截断优先级**（按序尝试，满足即停）：
1. **保留主句主谓完整**：主句的主语 + 谓语不可裁切。优先删除句尾的从属从句和修饰语
2. **若生词在从属从句中**：保留主句骨架（简化主语+谓语）+ 生词所在的完整从句。例如 `When I was a little boy, … → When I was a boy, the <b>tenderness</b> of smiling faces used to make up the radiance of the gifts I received.`（~140 字符）
3. **从后往前裁切**：优先删除句尾的 `, and…`、`, which…`、`, so…` 等追加性分句，比删除句首状语从句更不易丢失核心信息
4. **不得已时保留完整长句**：若上述规则无法产出 ≤150 字符的完整句子 → 保留完整原文（标注长度），sync_anki.py 会拒绝超长句子→返回重新处理

**绝对禁止**：
- 禁止产出以非首字母大写开头的片段（如 `the lights of…`）
- 禁止产出纯名词短语（无谓语动词）
- 禁止用 `…` 伪装片段为完整句子
- **禁止产出以连词开头的片段**：`and then, …`、`but they…`、`so that…` 等以并列/从属连词开头的片段不是完整句子。若截断后自然句首是连词 → 继续向前往自然句边界回溯，或放弃截断保留完整长句
- **禁止截断切掉 `<b>` 标签**：截断必须在 `<b>…</b>` 之后进行，绝不能把生词本身裁掉。若生词在句子末尾 1/3 处且截断会导致 `<b>` 丢失 → 改用 3.0c-3 扩展策略重找更短的句子，或保留完整长句
- **禁止以功能词结尾**：截断后的句子不能以介词（`from`、`with`、`at`、`for`…）、并列连词（`and`、`but`、`or`…）、助动词（`was`、`had`、`came` 作助动词时）结尾——这些词暗示从句未完。截断点必须在实词（名词、动词、形容词）或句末标点（`.!?"`）之后。若截断位置落在功能词后 → 继续往前回溯到上一个实词或放弃截断

**截断后自检**（每句截断后立即执行）：
1. `<b>…</b>` 标签完整存在且包裹正确的表面词形？
2. 句子是否以大写字母或 `"` / `'` 开头？（不含 `…` 开头的情况——`…` 开头的句子不通过 `sync_anki.py` 的 sentence 长度验证，因为 `len()` 计算含标签的完整字符串）
3. 句子含义是否自包含？（不依赖被裁切掉的上下文就能理解？）
4. 若上述任一为否 → 放弃截断，使用更短的替代句子（3.0c-3 扩展策略），或保留完整长句返回重处理

**翻译对应规则**：**`translation_cn` 必须只翻译截断后的最终 `sentence`**，不得翻译截断前的完整原文。若截断后句子缺少某部分内容，翻译也必须同步省略。

**源文本获取失败时：**
- curl 直链 + WebSearch/WebFetch 均无法获取 → **该批次所有单词跳过，不生成卡片**。Step 4 汇总中标明 `源文本不可用，N 个单词未生成`
- **禁止回退到词典例句**。词典例句脱离书中语境，对阅读理解没有帮助。卡片的价值在于"这个词在这本书的这个句子里是这个意思"，没有源文本就没有卡片

**完成后进入 Step 3.0f**——句子已从源文本提取并截断至最终长度，下一步机械翻译。

### Step 3.0f: DeepL 机械翻译（替代 Claude 翻译）

> **核心改进**：翻译从 Claude 知识工作改为 DeepL API 机械翻译。彻底消除三个问题：
> 1. Claude 翻译幻觉（凭空添加原文没有的内容）
> 2. 截断后翻译未同步更新（保留已裁掉内容）
> 3. 批量翻译时 Claude 注意力衰减导致对齐错误
>
> DeepL 输入什么翻译什么——截断后的短句不会带上已裁掉的内容，天然杜绝 alternately 模式。

**前置条件**：`DEEPL_API_KEY` 环境变量（免费 key 从 https://www.deepl.com/pro-api 获取，500,000 字符/月）。

```bash
# 若 DEEPL_API_KEY 未设置 → 跳过此步，翻译仍由 Claude 在 Step 3 完成
if [ -n "$DEEPL_API_KEY" ]; then
    <skill_dir>/.venv/bin/python3 <skill_dir>/scripts/translate_deepl.py /tmp/vocab-anki-input-<bookId>.json
fi
```

脚本行为：
- 读 JSON 中所有 `sentence`，剥离 `<b>` 标签后发送 DeepL（`target_lang=ZH`）
- 每批 50 句，遇批次失败逐句重试
- 翻译写回 `translation_cn` 字段
- 打印字符用量（对照 500,000/月配额）

**完成后进入 Step 3**——句子已提取并截断，翻译已由 DeepL 完成。Claude 工作收窄为：IPA + 释义 + 翻译质量抽查。

### Step 3: 生成内容（Claude 知识工作，范围收窄）

仅对 Step 1 筛出的 C 个单词生成内容。句子已在 Step 3.0 从源文本提取并截断，翻译已在 Step 3.0f 由 DeepL 完成（若 API key 未设置则由 Claude 在此步骤完成）。此步骤聚焦 IPA、释义、翻译质量抽查。对每个单词提供：

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 书中出现的**表面词形**——`<b>` 包裹什么就写什么。**绝不**填原形 | `blundering`（不是 `blunder`），`conceited`（不是 `conceit`），`pondered`（不是 `ponder`）|
| `lemma` | **派生形容词时必填，常规屈折变化可留空**。`sync_anki.py` 三层防护：(1) Claude 显式设置的 `lemma` **无条件信任**——填了就以此为准；(2) 若留空，`resolve_lemma()` 用 lemminflect + COCA 守卫自动还原；(3) **spaCy 读原句校验**——对 `-ed`/`-ing` 词，若判定为形容词则阻止还原。因此：派生形容词（`blundering`、`accomplished`、`distinguished` 等）→ 填 `lemma`；常规屈折（`attached`→`attach`、`burning`→`burn`）→ 留空让脚本处理 | `pondered`→留空（自动 `ponder`）；`accomplished`(adj)→`"accomplished"`；`blundering`(adj)→`"blundering"` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹 | `I felt awkward and <b>blundering</b>.` |
| `ipa` | 对应 **lemma** 的 IPA 音标。**cmudict 自动生成，Claude 仅在多发音词时用作投票参考**。未登录词时 Claude 提供兜底 | 单发音词留空；异读词填正确发音如 `/riːd/`（非 `/red/`） |
| `definition_cn` | **按句中实际用法释义**，不按原形常见义项，也不自动选择最常见的词典义。特别注意多义词的含义选择：同一个词在不同句子中可能是完全不同的意思。即使卡片展示原形，释义反映句中词性 | `blundering` 在 "awkward and blundering" 中→"笨拙的，跌跌撞撞的"（**不写**"犯大错"）；`conceited`→"自负的"（**不写**"自负"）；`thriftily` 在 "he must be treated thriftily" 中→"有节制地，有所保留地"（**不写**"节俭地"）|
| `translation_cn` | 整句的中文翻译。优先使用 Step 3.0f DeepL 翻译（若可用）；否则 Claude 生成（遵循翻译原则）。DeepL 翻译需抽查：通读 3-5 句确认语义正确、与截断后句子对齐 | `我于是对丛林中的冒险深深思索起来。` |

**例句规则（不变）：**
- 必须是书中真实句子，不是词典通用例句。句子来源只有一条路径：3.0c 源文本机械匹配
- **禁止凭记忆编造特定书的句子**——即使 Claude 认为自己"记得"某本书里的某句话，实际准确率极低（stroke 案例：自信地编造了 "He took a stroke with the oar"，该句在《老人与海》中根本不存在）。源文本没有 → 该词不生成卡片
- **禁止使用词典例句替代**——词典例句脱离书中语境，对阅读理解没有帮助
- 句子中出现的生词形式可能不同于原形（如 `straying` vs `stray`），用 `<b>` 包裹书中实际出现的词形。**`<b>` 必须包裹句中完整的表面词形，绝不能包裹原形后拼接剩余字母**——例如句中写的是 `considerably`，就写 `<b>considerably</b>`，**禁止**写 `<b>considerable</b>ly`（原形 `considerable` + 后缀 `ly`）。同理，句中写的是 `devoted`，就写 `<b>devoted</b>`，**禁止**写 `<b>devote</b>d`——脚本内置的 `resolve_lemma()` 会自行将 `word` 还原为原形用于 WordId 和卡片正面展示，**绝不可以在 `<b>` 或 `word` 字段中手动将表面词形替换为原形**。`word` 字段必须与 `<b>` 包裹的文本一致
- **`<b>` 目标词校验**：句子中 `<b>` 包裹的词必须是当前卡片的生词。若同一句中还出现了本牌组其他生词（如 `baobabs`），**绝不能**把 `<b>` 标到别的词上——生成后逐词确认 `<b>…</b>` 内的文本与 `word` 字段一致
- 例句应简洁：1-2 句，通常 ≤150 字符。**禁止**使用整段对话或长段落——仅提取目标词所在的核心句及其紧邻上下文，让学习者在 3 秒内定位到生词
- **以上规则由 `sync_anki.py` 在同步前自动校验**：句子长度 >150 字符、`<b>` 内容与 `word` 字段不匹配、必填字段（ipa/definition_cn/translation_cn）缺失均会拒绝同步并打印错误。尽早生成高质量内容，避免回滚重做

**卡片字段更新依赖规则（硬性要求）：**

Anki 卡片各字段之间存在数据依赖——修改一个字段时，依赖字段必须同步更新，否则产生不一致卡片（如新例句配旧音频、新单词配旧音标）。

| 修改的字段 | 必须同步更新的依赖字段 | 不需要更新的 |
|-----------|---------------------|------------|
| `lemma` | `ipa`（音标对应新 lemma）、单词音频（重新生成，TTS 读新 lemma）、`definition_cn`（释义需与新词形匹配） | `sentence`、`word`（`word` = `<b>` 文本不变，但卡片展示的是 lemma） |
| `word` | 同 `lemma`（`word` 变化通常意味着表面词形修正，需检查 lemma 是否也需更新） | `sentence` |
| `sentence` | 例句音频（重新生成）、`translation_cn`（翻译匹配新句）、`word`（= 新句 `<b>` 内文本）、`definition_cn`（新句可能改变词义） | — |

> **`word` vs `lemma`**：`word` 字段存储 `<b>` 中的表面词形（仅用于校验），卡片正面展示的是 **lemma**。改 `lemma` 不改 `word` 是常见操作（如派生形容词 `blundering` 设 `lemma: "blundering"` 阻止还原），此时 `word` 不变但 IPA、音频、释义都需更新。

**`definition_cn` / `translation_cn` 更新判断**：

| 变更 | definition_cn 是否需要更新 | 判断依据 |
|------|--------------------------|---------|
| 修复截断（句子变短，同语境） | 否 | 词义在句中未变 |
| 换到不同句子 | **检查** | 同一词在新句中可能是不同义项 |
| 修正 `word`/`lemma`（如 `heal`→`healer`） | **必须** | 词变了，释义对应不同词 |
| 拼写/大小写修正 | 否 | 词没变 |

**执行流程**：
1. 修改源 JSON 中的 `word`/`lemma` 或 `sentence` 字段
2. 重新运行 `sync_anki.py --prefetch` 生成新音频（被修改词的新音频覆盖旧文件）
3. 重新运行 `sync_anki.py --audio-dir <dir>` 上传新媒体并更新 Anki 卡片字段
4. 若是修复已在 Anki 中的单张卡片：用 AnkiConnect API 直接更新 `fields`（含 SentenceAudio/WordAudio），并调用 `storeMediaFile` 上传新媒体

**历史教训**：`alternately` 等 20 张卡片例句截断修复时只更新了 `Sentence` 字段，例句音频仍播放旧截断句，用户发现后才补传——此后作为硬性规则。

**同步后审计（Step 4 完成后必做）**：逐张检查 Anki 卡片，重点查三类问题：

1. **Word ≠ `<b>` 文本且不是合法原形还原**：`affect` + `<b>affects</b>` ✅（合理屈折），但 `heal` + `<b>healer</b>` ❌（`healer` 是独立名词不是屈折形式）、`rob` + `<b>robber</b>` ❌（同理）。判断标准：若 `<b>` 词在 COCA 中作为独立词条且词性与 Word 不同，则不应还原为 Word。
2. **Word 被截断**：`lavend`/`silv`/`weath`/`nause`/`sev`/`jag`/`unarm`/`trouser`——原形不完整，需修正为完整词形。
3. **Word 大小写异常**：`Amen`/`Champion`/`Dick`/`Mike`/`Virgin` 等专有名词或句首大写泄漏到 Word 字段——应统一为小写（非专有名词时）。

审计命令：
```bash
curl -s http://localhost:8765 -d '{"action":"findNotes","version":6,"params":{"query":"deck:\"牌组名\""}}' | python3 -c "..."  # 拉取所有卡片，比对 Word 与 <b> 文本
```

**翻译原则：**

> 准确、自然、可追溯。每个关键词汇在中文里要有对应，让学习者能从句子的中文字面反推出英文结构。不要逐字死译，也不要重新创作。

- **关键词映射可追溯**：`absence of reproaches` → "没有一句责备的话"（`absence`→"没有"、`reproaches`→"责备的话"），而不是"毫无责备之意"（丢失了 `absence` 的映射）
- **句式按中文习惯调整**：英文的代词、从句、被动语态大胆打破，换成中文流水句。但词义不走样
- **动词优先选用与英文义项直接对应的词**：`intimated` → "暗示"（而非"婉转地表示"），`linger` → "徘徊"（而非"流连"），确保学习者能根据中文反查英文原词
- **不要重新创作**：翻译的目的是辅助理解英文原句，不是独立的中文美文
- **多义词语境陷阱（common sense trap）**：英文中大量词汇有多个义项，不要自动选择最常见或最熟悉的义项。回到原文判断该词在此句中具体表达什么意思。例如 `thriftily` 在 "he must be treated thriftily" 中意为"有节制地，有所保留地"（sparingly, with restraint），而非"节俭地"（frugally, economically）——节俭适用于钱物，不适用于对人的"对待"。每次遇到不确定的词，先用中文问自己"这句话里这个词到底在说什么"，再选译义。若多个义项在中文中都说得通，优先选最能体现原文动作/状态特征的那个

**IPA 规则：**
- **IPA 必须对应 lemma（卡片展示词）**——卡片正面显示的是原形，音标应与卡片展示词一致
- **IPA 由 cmudict（CMU Pronouncing Dictionary，134K 词）自动生成**——`sync_anki.py` 内置 ARPAbet→IPA 转换。Claude 不再需要凭记忆生成 IPA
- **多发音词（heteronym）**：cmudict 提供候选发音（如 `read` 的 `/red/` 和 `/riːd/`），Claude 的 `ipa` 字段用作投票选出正确发音。若 Claude 未填 IPA，取 cmudict 第一候选
- **未登录词**：cmudict 查不到的词退回 Claude 的 `ipa` 字段
- 单词音频由 Edge TTS 默认发音生成（不使用 SSML `<phoneme>`——`edge_tts.Communicate` 内部对输入做 `escape()` 后再用 `mkssml()` 包一层 `<speak>`，外部 SSML 会被二次转义导致 TTS 朗读 XML 源码）
- IPA 缺失时跳过单词音频生成，卡片仍正常创建（例句音频正常生成）

**执行策略：分批写入，禁止一次性思考全部单词**

> **核心问题**：若试图在 thinking block 中为 50+ 单词逐一回想并验证例句+IPA+释义+翻译，thinking 会持续 2-3 分钟无任何输出。**禁止预先思考全部单词——按批次边写边想，每批写完再想下一批。**
>
> **执行铁律**：读完 pipeline 输出后，**先执行 Step 3.0 拉取源文本**，从源文本中机械匹配所有单词的句子。然后在写入 JSON 时直接填入已提取的句子。不要在 thinking block 中回忆例句——句子已从源文本检索到。

**批次规则：**
- ≤20 词：单批写入
- 21-40 词：分 2 批，每批 ~20 词
- 41-60 词：分 3 批，每批 ~20 词
- 60+ 词：分 4+ 批，每批 ~15 词
- 每批按字母序排列该批单词

**派生形容词 COCA 复查：**

`lemmatize_word` 将派生 adj 还原为词根（`blundering`→`blunder`、`conceited`→`conceit`），词根在 COCA 中放行。对于此类词有两层防护：

1. **Claude 在自查清单中逐批校验**：确认句中用法为派生形容词 → 显式设置 `lemma`（如 `"lemma": "blundering"`）
2. **spaCy 在同步前做句子级校验**：对 `-ed`/`-ing` 词，spaCy 读原句判断词性——若判定为形容词，阻止 `resolve_lemma()` 的还原（见 `_process_one_word()`）

若派生形容词的自身不在 COCA 20000 中 → **不生成卡片**，加入 `excluded` 数组，reason 为 `"派生形容词，不在 COCA 20000 中"`。

> 例：`blundering`(adj) 不在 COCA → 排除。`distinguished`(adj) 在 COCA → 生成，Claude 设 `lemma: "distinguished"`，spaCy 读 `a <b>distinguished</b> fisherman` 确认为形容词 → 不还原为 `distinguish`

**每批自查清单（写入 JSON 后、下一批开始前必做）：**

每批写入完成后，逐词检查以下四项，发现错误立即修正：

1. **lemma 正确性**：脑中过一遍 `lemmatize_word(word)` 的返回结果。结果词性与句中实际用法一致（屈折变化）→ `lemma` **留空**，脚本自动还原；不一致（派生 adj 被当屈折）→ 必须显式覆写 `lemma`。例如 `blundering`(adj)→lemmatize→`blunder`(v) 词性不对，覆写 `lemma: "blundering"`；`distinguished`(adj)→lemmatize→`distinguish`(v) 词性不对，覆写 `lemma: "distinguished"`；`pondered`(v)→lemmatize→`ponder`(v) 正确，`lemma` 留空。**绝不在 `lemma` 字段中填写与 `word` 相同的表面词形**——留空让脚本处理，填表面词形反而阻止自动还原
2. **IPA 对应性**：每个 IPA 是否对应 `lemma`（卡片展示词）的正确发音？异读词（如 `intimate`）必须根据释义选择 `/ˈɪntɪmət/`(adj) 或 `/ˈɪntɪmeɪt/`(v)
3. **释义词性对齐**：`definition_cn` 是否反映了句中实际用法的词性？`blundering` adj→"笨拙的"（非"犯大错"）；`conceited` adj→"自负的"（非"自负"）
   - **被动语态 vs 形容词检查**：`-ed` 分词在句中可以是动词过去分词（被动语态）或形容词（情感/状态）。判断标准分三层：
     1. **`by` + 施事者** → 被动语态，动词。例：`His back was <b>bent</b> with the weight` → `bent` 是 `bend` 的过去分词，`v. 被压弯`（**不标** `adj. 弯曲的`）
     2. **`be X-ed to <verb>`** → 形容词。情感形容词 + to-infinitive 是英语中固定模式，无施事者。例：`your friends will be properly <b>astonished</b> to see you laughing` → `adj. 惊讶的，吃惊的`（**不标** `v. 使惊讶`）。同类：`surprised to hear`、`delighted to learn`、`disappointed to find`
     3. **`be X-ed` 无施事者、无 to-infinitive** → 酌情判断：描述情感/状态（`He was <b>embarrassed</b>.` → adj），或描述动作结果（`The window was <b>broken</b>.` → v.）。若有后续从句说明原因（`that…`、`because…`），通常为形容词
     4. **X-ed 直接修饰名词** → 形容词（如 `a <b>distinguished</b> fisherman`）
4. **word 字段一致**：`word` 是否 = `<b>` 包裹的文本 = 句中出现的形式？
5. **语义情境对齐（多义词义项验证）**：对每个词，重读 sentence 中的上下文，确认 `definition_cn` 和 `translation_cn` 选择了该词在此句中的正确义项，而非其最常见词典义。执行以下验证：
   - **代入验证法**：将 `definition_cn`（去除"的/地/了"等标记）代入原英文句替换原词，看代入后的概念是否通顺合理。若替换后句子意思不通或产生逻辑矛盾，说明义项选错。例如 "he must be treated thriftily" → "节俭地对待他" 不通（对人不能"节俭"），说明应换义项
   - **义项枚举法**：脑中快速列出该词你知道的 2-3 个义项，逐一用代入验证法测试，选出最合理的一个
   - **跨句一致性检查**：若同一词在牌组中多次出现（不同句子），确认每个句子中该词的义项独立判断——前一句是"节俭"不意味着本句也是"节俭"
   - 发现定义/翻译与句子语境冲突时，修正后继续，不要遗留到下一批
6. **sentence-translation 对齐**：逐词检查 `sentence` 的英文语义单元，确认 `translation_cn` 中**每个中文语义元素在英文句中都有对应**。若翻译中出现英文句子里不存在的内容（如中文有「共同构成了我所收到礼物的光芒」但英文只有 `…the tenderness of smiling faces…`）→ 句子截断有误或翻译凭空添加。立即修正句子或同步裁切翻译，直到二者语义完全对齐
   - **截断后翻译同步更新**：句子经 3.0e 截断后，**必须重新审视翻译**——原翻译基于完整长句，截断后句子变短、信息减少，翻译也须同步裁剪。**禁止**截断后保留原翻译——会出现翻译信息多于句子实际内容的情况（如 `alternately` 的句子只剩 `swinging with each arm alternately on the…` 但翻译包含"他喊了一声，双手猛击，收回一码线"等已裁掉的内容）。正确做法：截断后立即重新翻译截断句
   - **双向对齐验证**（每句必做，不仅是截断句）：
     1. **英→中**：圈出英文句中的实词（名词、动词、形容词、副词），确认每个在中文翻译中都有对应或合理省略（如代词、冠词可省）。**禁止**翻译漏掉整个分句（如 `and he carried the fish in his right hand` 完全消失）。
     2. **中→英**：圈出中文翻译中的实词，确认每个在英文句中都有对应。**禁止**翻译出现英文中没有的具体事物/动作（如英文无 `head` 但翻译出现"头"——`aboard` 案例）。
     3. 任方向不匹配 → 修正翻译或重新截断句子，直到双向对齐

**写入流程：**

- **推荐方案（Python json.dump）**：整份 JSON 一次写入——Python 的 `json.dump` 无 Unicode 归一化问题，无需分批。
  ```bash
  python3 << 'PYEOF'
  import json
  data = { "book_title": "...", ... }
  with open('/tmp/vocab-anki-input-<bookId>.json', 'w', encoding='utf-8') as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
  PYEOF
  ```
- **备选方案（Write 工具分批）**：仅当翻译不含中文引号时可用。
  1. 第一批：`Write` 完整 JSON（含 `book_title`/`book_author`/`book_id`/`excluded` + 第一批 `words`）
  2. 后续批次：`Read limit=5` 当前文件 → `Edit` 在 `words` 数组末尾追加新单词（在 `]` 前插入）
     - 若 Edit 匹配不精确，改用 `Write` 全量覆盖（Read 完整文件后重写）

**注意**：第一批之前仍需 `rm -f + touch + Read limit=3` 初始化文件。后续批次只需 Read + Edit/Write。

- **不再使用 SubAgent**：SubAgent 启动慢（权限确认、模型初始化），常误触发 WebSearch 浪费额度，多个 agent 的协调开销远超串行生成的实际耗时
- **句子来源**：所有例句均通过 Step 3.0 从源文本机械提取。源文本不可用 → 跳过该批次所有单词，Step 4 汇总中标明

**性能说明：**
- **分批写入是关键性能优化**：每批 ~15-20 词，单批 thinking ~10-15s + 写入 ~2s，总耗时 30-60s（vs 单次思考 2-3 分钟无输出）
- **JSON 写入优先用 Python `json.dump`**：Write 工具可能将中文弯引号（`""`）归一化为 ASCII `"`（U+0022），破坏 JSON 定界符。Python `json.dump` 无此问题，且 `ensure_ascii=False` 保留中文原文。推荐用 Bash heredoc 调用 Python：
  ```bash
  python3 << 'PYEOF'
  import json
  data = { ... }
  with open('/tmp/vocab-anki-input-<bookId>.json', 'w', encoding='utf-8') as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
  PYEOF
  ```
- 若翻译中不含中文引号等特殊字符，仍可用 Write 工具（更快）；否则切到 Python
- **Write 工具要求文件已被 Read 过**（当前会话上下文中有该文件），否则写入报错。因此第一批写入前需三步（用 Python 可只做 touch + Read）：
  1. `Bash rm -f /tmp/vocab-anki-input-<bookId>.json` — 清理上次运行残留的旧文件，避免 Read 时加载无用的旧 JSON 到上下文
  2. `Bash touch /tmp/vocab-anki-input-<bookId>.json` — 创建空文件
  3. `Read /tmp/vocab-anki-input-<bookId>.json limit=3` — 将会话上下文注册该文件（满足 Write 的前提条件）；空文件仅 3 行，几乎不占上下文
  4. `Write /tmp/vocab-anki-input-<bookId>.json` — 写入第一批（含完整 JSON 结构）
- `rm` + `touch` 确保每次运行都从干净空文件开始，不会加载上次的完整旧 JSON
- 后续批次：`Read limit=5` 定位 `words` 数组末尾 → `Edit` 追加新词 → 下一批

**完成后 JSON 格式：**
```json
{
  "book_title": "小王子（英文版）",
  "book_author": "圣埃克絮佩里",
  "book_id": "22720170",
  "deck_name": "小王子（英文版） (圣埃克絮佩里)",
  "words": [
    {"word": "pondered", "lemma": "ponder", "ipa": "/.../", "sentence": "...", "definition_cn": "...", "translation_cn": "..."}
  ],
  "excluded": [
    {"word": "abash", "reason": "不在 COCA 20000 中"}
  ]
}
```
- `book_title` 和 `book_author` 来自 Step 1 的解析结果（已有牌组则来自牌组名，否则来自微信读书 API）
- `book_id` 为微信读书 bookId
- `deck_name`：**从 Step 0b 的 `{牌组名: bookId}` 映射中反查**。若 bookId 已有牌组 → 填入 Anki 中实际牌组名（确保新旧卡片归入同一牌组）；若新书无已有牌组 → 用 `{title} ({author})` 拼接（**去掉作者国籍前缀如 `[美]`**）
- `ipa` 由 cmudict 自动生成；Claude 仅在多发音词时提供投票参考
- `excluded` 数组从 Step 1 `--json-out` 输出的 JSON 文件中读取，**使用 `lemma` 字段**（非 `rep`）填入 `word`，确保排除词以原形展示；`reason` 字段直接沿用
- **此步骤不展示样卡，不询问用户**

### Step 3.5: 预下载音频（并发，不依赖 Anki）

> 在确认之前提前下载所有音频。此步骤不连 Anki，纯并发 HTTP 下载。

```bash
# 若 .venv 不存在则创建（仅首次）
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 并发生成全部音频 → 保存到临时目录 → 输出 AUDIO_DIR 路径
<skill_dir>/.venv/bin/python -u <skill_dir>/sync_anki.py \
  /tmp/vocab-anki-input-<bookId>.json \
  --prefetch -v
```

输出末尾包含 `AUDIO_DIR=<path>` 行，提取路径供 Step 4 使用。

展示预下载结果：
```
音频预下载完成：word✓ 64/64, sent✓ 63/64（1 句失败）
```
失败项标出但不阻塞——音频失败降级为纯文本。

### Step 4: 最终确认 + 同步（唯一确认点）

**4a. 展示最终汇总（含音频预下载状态）：**

- **新增排除**：本轮 COCA 检查中新发现不在表中的词（**原形** + 原因）。使用 `excluded[].word`（已是原形）
- **音频状态**：Step 3.5 结果（如 `word✓ 64/64, sent✓ 62/64`）
- **本次新增**：将同步的单词列表（仅单词**原形**，不展示样卡）。使用 `words[].lemma` 字段展示；若未提供 `lemma` 则从 filter_pipeline.py `--json-out` 的 `in_coca` 数组按 `rep` → `lemma` 反查
- **源文本校验状态**：已通过源文本校验的单词数 / 总数。源文本不可用致跳过的单词数；源文本中未匹配到单个词的标 `⚠️`
- **lemma 覆写数量**：本轮 Claude 显式覆写了几个 lemma（`lemmatize_word` 结果被纠正）
- Anki 已有的词仅一句话带过数量，不列出

**4b. 空跑判定：**

若本次新增为空 **且** 新增排除为空 → 直接回复「没有新的划线生词」，终止流程，**不询问用户**。

**4c. 唯一确认：**

展示汇总后，仅问一次：「确认同步？」

**4d. 执行（音频已预下载，秒级完成）：**

> 音频已在 Step 3.5 预下载到临时目录。同步阶段仅上传媒体 + 创建卡片，无需等待音频生成。
> 脚本启动时自动校验 JSON 质量（句子长度、`<b>` 匹配、必填字段），违规则拒绝同步。
> 超时按每词 3s（上传 ~1s + 余量），下限 60s。由于很快，通常前台直接运行即可。

```bash
WORD_COUNT=$(python3 -c "import json; print(len(json.load(open('/tmp/vocab-anki-input-<bookId>.json'))['words']))")
SYNC_TIMEOUT=$(( WORD_COUNT * 3 + 30 ))
[ "$SYNC_TIMEOUT" -lt 60 ] && SYNC_TIMEOUT=60

timeout $SYNC_TIMEOUT <skill_dir>/.venv/bin/python -u <skill_dir>/sync_anki.py \
  /tmp/vocab-anki-input-<bookId>.json \
  --audio-dir <AUDIO_DIR_FROM_STEP_3.5> \
  -v
```

**同步超时处理：**
- 正常完成 → 展示同步结果
- 超时退出（exit 124）→ 告知用户：「同步脚本超时。可能原因：AnkiConnect 响应慢或网络不畅。重试即可。」
- 非零退出码 → 打印 stderr，告知具体错误

#### 同步详情（sync_anki.py）

1. Step 3.5 (`--prefetch`): 并发生成全部音频 → 保存到临时目录 + manifest.json → 打印 `AUDIO_DIR=<path>`
2. Step 4 (`--audio-dir <dir>`): 从目录加载预生成音频 → 连 AnkiConnect → 查已有卡片 → 上传媒体 → 添加新卡片
3. 对每个词调用 `lemmatize_word()` 还原为原形 → 用原形构建 WordId、卡片词、音频文件名
4. **音频命名**：`{lemma}_{bookId}_word.mp3` / `{lemma}_{bookId}_sent.mp3`——加入 `bookId` 命名空间，防止不同牌组的同名单词（异读词 `wound`、不同书的不同例句）在 Anki 全局 `collection.media` 中互相覆盖
5. **单词音频**：Edge TTS 默认发音（IPA 仅用于卡片显示）；IPA 缺失时跳过单词音频
6. **例句音频**：Edge TTS 朗读
7. **已有卡片完全不动**，保留复习进度和调度数据
8. **触发 AnkiWeb 同步**：卡片添加完成后自动触发 `sync` 操作，将新卡片同步到 AnkiWeb。此操作为 fire-and-forget——成功响应仅表示 Anki 已接受请求，不代表 AnkiWeb 已收到数据。若 Anki 弹出冲突解决对话框，同步可能静默排队。使用 `--no-ankiweb-sync` 跳过此步骤

牌组名优先从 JSON `deck_name` 字段读取（Claude 在 Step 3 从 Step 0b 的 `{牌组名: bookId}` 映射反查填入）。未提供时回退 `--deck` 参数；都未提供才自动拼接。

## 卡片格式

### 正面
```
┌──────────────────────────┐
│                          │
│       pondered           │  ← 40px 粗体
│                          │
│ ─────────────────────── │
│                          │
│  I pondered deeply,      │  ← 例句，生词蓝色加粗
│  then, over the          │
│  adventures of the       │
│  jungle.                 │
│                          │
└──────────────────────────┘
```

### 背面
```
┌──────────────────────────┐
│  (正面内容重复)           │
│ ─────────────────────── │
│                          │
│  IPA                     │
│  /ˈpɒndər/               │
│                          │
│  释义                     │
│  沉思，深思                │
│                          │
│  例句翻译                  │
│  我于是对丛林中的冒险        │
│  深深思索起来。             │
│                          │
│  🔊 word  🔊 sentence    │
│                          │
└──────────────────────────┘
```

## 异常处理

| 情况 | 处理 |
|------|------|
| 没有划线 | 分两种情况：(1) Step 1d 报错退出（stderr 含 `ERROR:`）→ API 响应无效，检查 `$WEREAD_API_KEY` 拼写、bookId 是否正确，重试；(2) Step 1d 正常输出 `SUMMARY: 0 highlights` → 确实没有划线，提示用户在微信读书中标记生词后再试 |
| 划线全是整句 | 提示："划线看起来是完整句子而非生词。仍然可以生成牌组，是否继续？" |
| 源文本不可用 | curl 直链 + WebSearch/WebFetch 均无法获取书中文本 → **该批次所有单词跳过**，Step 4 汇总中标明 `源文本不可用，N 个单词未生成`。禁止回退到词典例句 |
| 超过 50 个单词 | Claude 直接生成全部内容 + 并发音频（8 线程），一次写入 JSON |
| 脚本运行失败 | 检查依赖安装、网络连接，打印错误信息 |
| 音频生成失败 | Edge TTS 不可用时自动跳过音频，生成纯文本卡片 |
| `WEREAD_API_KEY` 未设置 | 提示用户设置：`export WEREAD_API_KEY=<your-key>` |
| AnkiConnect 不可达 | 提示启动 Anki 并安装 AnkiConnect 插件后重试；若为远程环境，提示使用 `ssh -R 8765:localhost:8765` 建立反向隧道 |
| 模型不在 Anki 中 | 提示先通过 AnkiConnect 同步一次建立模型 |
| 牌组中全是新词 | 全部添加，和首次导出效果一样 |
| 同步脚本超时 | 提示原因（网络慢/词多/Anki 响应慢），建议 `--no-audio` 或分批 |
| 没有新划线生词 | 直接告知用户「没有新的划线生词」，流程自动结束 |

## 输出

- 打印新增/跳过的单词数量
- 用户直接在 Anki 中看到新卡片出现
- 复习进度完整的牌组不受影响

## 脚本清单

| 脚本 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `utils.py` | 共享工具模块 — lemmatize_word, edge_tts_bytes/file, safe_filename | — | 工具函数 |
| `sync_anki.py` | 增量同步到 Anki — 含 `resolve_lemma()` 自动原形还原 + spaCy 句子级校验 | JSON + AnkiConnect | 直接添加卡片到 Anki |
| `ankiconnect.py` | AnkiConnect 客户端模块 | (内部使用) | AnkiConnect API 封装 |
| `filter_pipeline.py` | 合并过滤流水线 — 标点/大小写清理 → lemmatize → Anki 去重 → COCA 检查。自动剥离句边界标点（`vexed.`→`vexed`）并归一化非全大写词为小写（`Clad`→`clad`）。透传章节信息（`chapterUid` + `chapterTitle`）供 Step 3.0 章节优先匹配 | WeRead API JSON (stdin) | 过滤结果 (stdout) + 结构化 JSON (--json-out，含 `chapters` 字段) |
| `lib/coca.py` | COCA 词频查询 — 三层策略：直接 set 查找 + lemminflect（仅接受原形严格短于输入词的映射，如 `pondered`→`ponder`；同长映射如 `abode`→`abide` 被拒，避免名词误映射到无关动词）+ 后缀剥离兜底做派生归一（`indulgently`→`indulgent`） | 单词 → set 查找 + lemminflect + 后缀剥离 | 是否在 COCA 频率表中 |
| `lib/data/coca_freq.txt` | COCA 词频数据（18,964 词，频率排序） | — | 单一数据源，同时服务 set 查找和频率分级 |
| `scripts/match_sentences.py` | Step 3.0 机械句子匹配 — 读过滤 JSON + 源文本，提取含生词的完整句子并用 `<b>` 标签标记。强制 3.0e 截断规则（禁止从句首裁切、禁止产出片段）。替代 Claude 人工回忆模式 | 过滤 JSON + 源文本 | 带 `<b>` 标签的句子 JSON |
| `tests/` | pytest 单元测试套件（233 tests）——覆盖词形还原、COCA 查询、LLM 输出拦截、章节解析、IPA 生成 | — | 回归防护 |

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译、IPA），Python 做机械工作（HTTP、TTS、同步）。句子提取由 Step 3.0 源文本检索完成，不依赖 Claude 回忆
- **源文本检索替代回忆**：例句不再依赖 Claude 记忆生成，改为从网上拉取书中实际文本后机械匹配。Claude 的知识工作从「回忆句子+翻译+IPA」收窄为「翻译+IPA」，消除最易出错的环节
- **curl 优先于 WebFetch**：源文本拉取优先用 `curl -sL` 直链下载纯文本文件（Internet Archive、Project Gutenberg 等公版书站）。WebFetch 有严格引用字数限制（~125 字符/条），不适用于全书文本拉取，仅用作 curl 失败时的逐章兜底方案
- **章节优先匹配**：filter_pipeline.py 透传 WeRead 的 `chapterUid`/`chapterTitle` 到 JSON 输出，Step 3.0 优先在单词所属章节范围内搜索句子，避免同名异义词匹配到书中其他位置（如 `fair` 在"公平的"和"集市"两个义项间不会串章）。章节边界不确定时回退到全文本搜索
- **源文本格式兼容**：DOCX、PDF、HTML 均可作为源文本。纯文本提取后做机械匹配。常见源：thephilosopher.net 的 DOCX、archive.org 的纯文本、QQ 阅读等
- **表面词形严格匹配**：搜索时用 `\bword\w*\b` 会误匹配不同词（如 `lung` 搜索匹配到 `lunged`，这是 `lunge` 的过去式而非 `lung`）。必须验证匹配到的词与目标词形一致（大小写不敏感），不一致时排除

## 案例：老人与海牌组重建

2026-06-30 检测发现《老人与海》牌组 **245/327（75%）的例句是 Claude 回忆编造的**。句子风格正确、主题匹配、语法通顺——但源文本中不存在。典型：

| 编造句 | 问题 |
|--------|------|
| `He took a stroke with the oar.` | 书中唯一出现是 `strokes`（金枪鱼尾巴拍击），与船桨无关 |
| `He did not understand the behaviour of the shark.` | 英式拼写 `behaviour`，书中是美式 `behavior` |
| `He heard the boom of the breaking mast.` | 书中桅杆从未断裂 |

**修复流程**：
1. 从 thephilosopher.net 下载 DOCX（133K 单词）→ Python 提取纯文本
2. 245 个单词逐词在源文本中搜索 → 提取所在完整句子
3. 164 句无需截断，75 句 >150 字符按 3.0e 规则截断，6 个词形变体手动定位
4. 批量更新 Anki Sentence/Word/TranslationCN + 重新生成 SentenceAudio（327 条 TTS）

**关键教训**：
- 回忆模式下 Claude 的句子"看起来对"但实际错误率高得惊人
- 源文本机械匹配是唯一可靠的句子来源
- 源文本不可得 → 不生成卡片，这个硬规则必须执行
- **过滤前置**：Anki 去重和 COCA 频次检查在生成内容**之前**完成，避免浪费 Claude 精力。Anki 去重先于 COCA：已在牌组中的词不受 COCA 频次变化影响
- **音频并发**：多线程（16 workers）并发生成音频（Step 3.5），将音频生成压缩到秒级
- **音频命名空间**：文件名含 `bookId`（`{lemma}_{bookId}_word/sent.mp3`），防止异读词和不同书例句在全局媒体库中冲突
- **确认前置音频**：音频在确认前预下载（`--prefetch`），确认后秒级同步（`--audio-dir`），用户不被阻塞
- **原形还原（spaCy + lemminflect 双层）**：`resolve_lemma()` 用 lemminflect + COCA 守卫做基础还原；`_process_one_word()` 中 **spaCy 读原句**判断 `-ed`/`-ing` 词的实际词性——若为形容词则阻止还原。Claude 显式设置的 `lemma` 无条件信任。全文过滤阶段 `build_spacy_map()` 一次性 parse + `lemmatize()` O(1) 查表，无手工词表
  - 两层均使用 `len(lemma) < len(word)` 作为准入条件：同长映射（`abode` n.→`abide` v.）被拒，避免跨词性误判。不同长映射正常通过（`crammed`→`cram`、`went`→`go`）。同长不规则变化（`ran`→`run`、`sat`→`sit`）同为已知限制，但这些词属基础词汇，实际划线中极少出现
- **bookId 桥接**：Anki 卡片 WordId 天然包含 bookId（`{lemma}_{bookId}`），用于精确关联微信读书，替代不可靠的书名匹配
- **一次性确认**：整个流程仅在最终同步前确认一次，中间步骤不打断
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范；Python 脚本间提取共享 `utils.py` 消除重复代码
- **故障降级**：音频获取失败不阻塞整体流程；同步超时有明确提示和建议
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响
- **IPA 零网络依赖**：Claude 从训练数据直接生成 IPA 用于卡片显示，无外部 IPA API 依赖。单词音频由 Edge TTS 默认发音生成（SSML `<phoneme>` 不可用——`edge_tts` 库内部二次转义导致 TTS 朗读 XML 源码）

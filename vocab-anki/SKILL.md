---
name: vocab-anki
description: >
  Generate Anki vocabulary flashcard decks from WeRead (微信读书)
  English book highlights. Syncs directly to Anki via AnkiConnect plugin.
  Use when user wants to create Anki cards from WeRead highlights, e.g.
  "/vocab-anki The Little Prince" or "为这本书的划线生词生成 Anki 牌组".
  Integrates with weread-skills for data; Claude does knowledge work
  (sentences, translations), Python scripts handle audio + sync.
---

# vocab-anki — 英文书词汇 Anki 牌组生成

将微信读书英文原版书的划线生词通过 AnkiConnect 直接同步到 Anki，嵌入发音音频。
自动对比已有卡片，仅添加新词，保留学习进度不受影响。

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
- 若有卡片 → 对每个使用 "Vocabulary Card (WeRead)" 模型的牌组，通过以下优先级获取 `bookId`：
  1. **优先查 meta manifest 卡片**：`WordId` 以 `__META__` 开头，格式固定 `__META__{bookId}`，专为存储书籍元数据设计，解析最可靠
  2. **fallback 查普通单词卡片**：`WordId` 格式 `{lemma}_{bookId}`
  
  从 `WordId` 末尾 `_{bookId}` 解析出 `bookId`，形成映射表：

```
{牌组名: bookId}
```

**目的**：用 bookId 作为 Anki ↔ 微信读书的精确桥接。meta manifest 卡片是书籍元数据的权威来源；普通单词卡片为 fallback。无需额外存储——每张卡片的 WordId 天然包含 bookId。

> **⚠️ Anki 搜索引号规则**：牌组名含 `()`、空格等特殊字符时，Anki 会误解析为分组/分隔符，必须用双引号包裹：`deck:"牌组名"`。
> **优先用 `tag:meta` 搜索 meta manifest**，彻底绕过牌组名字符问题——meta manifest 卡片始终带 `meta` 和 `weread` 标签：
> ```bash
> # 推荐：用 tag 搜索所有 meta manifest 卡片，无需指定牌组名
> curl ... -d '{"action":"findNotes","version":6,"params":{"query":"tag:meta"}}'
> # 然后通过 cardsInfo 查每张卡所属牌组，解析 WordId 提取 bookId
> ```
> 若直接搜索牌组内的普通卡片，必须给牌组名加双引号：`deck:"小王子（英文版） (圣埃克絮佩里)"`。

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
> 原形提取 → Anki 去重（含 meta manifest）→ COCA 检查。
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
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_pipeline.py --anki <bookId> --book-id <bookId> --json-out /tmp/vocab-anki-filtered-<bookId>.json
```

- `--anki <bookId>`：启用 Anki 去重（查已有卡片 + meta manifest）；若 Step 0b 确认全库 0 张 Vocabulary Card 笔记，可省略此 flag 跳过 Anki 查询
- `--book-id <bookId>`：传递给脚本用于 meta manifest 的 bookId
- `--json-out <path>`：将过滤结果写入结构化 JSON 文件，供 Step 3 Claude 直接读取填充 `excluded` 数组，避免手动转录

输出分为五段：`SUMMARY:` 行、`---IN_COCA---` 表、`---EXCLUDED---` 表、`---ANKI_SKIPPED---` 表（Anki 已有卡片，仅当存在时出现）、`---META_EXCLUDED---` 表（meta manifest 历史排除词，仅当存在时出现）。同时写入对应的结构化 JSON 到 `--json-out` 路径。

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

> Anki 去重先于 COCA：已在牌组中的词直接保留，不受 COCA 频次影响。历史排除词（存储在 meta manifest 中）也跳过，不再重复 COCA 检查。COCA 仅对真正的新词做筛。所有检查均为本地/本地网络查询（~0.5s），无需缓存。

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

**翻译对应规则**：**`translation_cn` 必须只翻译截断后的最终 `sentence`**，不得翻译截断前的完整原文。若截断后句子缺少某部分内容，翻译也必须同步省略。

**源文本获取失败时：**
- curl 直链 + WebSearch/WebFetch 均无法获取 → 回退到回忆模式，Step 4 汇总中标明「源文本不可用，例句未校验」

**完成后进入 Step 3**——句子已从源文本提取并截断至最终长度。Claude 基于截断后的 sentence 生成 IPA + 释义 + 翻译。

### Step 3: 生成内容（Claude 知识工作，范围收窄）

仅对 Step 1 筛出的 C 个单词生成内容。句子已在 Step 3.0 从源文本提取，此步骤聚焦 IPA、释义、翻译。对每个单词提供：

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 书中出现的**表面词形**——`<b>` 包裹什么就写什么。**绝不**填原形 | `blundering`（不是 `blunder`），`conceited`（不是 `conceit`），`pondered`（不是 `ponder`）|
| `lemma` | **派生形容词/特殊覆写时必填，常规屈折变化留空即可**。`sync_anki.py` 内置两层防护：(1) `resolve_lemma()` 自动还原（`attached`→`attach`、`burning`→`burn`、`closest`→`close`、`chosen`→`choose`）；(2) **spaCy 句子级校验**——对 `-ed`/`-ing` 词读一遍原句，若判定为形容词则阻止还原（如 `a distinguished fisherman`→保持 `distinguished`，不退 `distinguish`）。因此 Claude **仅在**派生形容词（`blundering` adj.、`conceited` adj.、`wicked` adj. 等）时显式设置 `lemma`。若不确定，脑中过一遍 `lemmatize_word(word)` 的结果：词性与句中用法一致→**留空**；不一致→显式覆写 | `pondered`→留空（自动 `ponder`）；`blundering`(adj)→`"blundering"`；`distinguished`(adj)→`"distinguished"` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹 | `I felt awkward and <b>blundering</b>.` |
| `ipa` | 对应 **lemma（卡片展示词）**的 IPA 音标，**不是**对应 `word`（表面词形）| `lemma=blundering`→`/ˈblʌndərɪŋ/`；`lemma=ponder`→`/ˈpɒndər/` |
| `definition_cn` | **按句中实际用法释义**，不按原形常见义项，也不自动选择最常见的词典义。特别注意多义词的含义选择：同一个词在不同句子中可能是完全不同的意思。即使卡片展示原形，释义反映句中词性 | `blundering` 在 "awkward and blundering" 中→"笨拙的，跌跌撞撞的"（**不写**"犯大错"）；`conceited`→"自负的"（**不写**"自负"）；`thriftily` 在 "he must be treated thriftily" 中→"有节制地，有所保留地"（**不写**"节俭地"）|
| `translation_cn` | 整句的中文翻译（遵循翻译原则） | `我于是对丛林中的冒险深深思索起来。` |

**例句规则（不变）：**
- 必须是书中真实句子，不是词典通用例句
- 如果对该书不够熟悉，无法回忆真实句子 → 如实告知用户，并提供词典例句作为替代
- 句子中出现的生词形式可能不同于原形（如 `straying` vs `stray`），用 `<b>` 包裹书中实际出现的词形。**`<b>` 必须包裹句中完整的表面词形，绝不能包裹原形后拼接剩余字母**——例如句中写的是 `considerably`，就写 `<b>considerably</b>`，**禁止**写 `<b>considerable</b>ly`（原形 `considerable` + 后缀 `ly`）。同理，句中写的是 `devoted`，就写 `<b>devoted</b>`，**禁止**写 `<b>devote</b>d`——脚本内置的 `resolve_lemma()` 会自行将 `word` 还原为原形用于 WordId 和卡片正面展示，**绝不可以在 `<b>` 或 `word` 字段中手动将表面词形替换为原形**。`word` 字段必须与 `<b>` 包裹的文本一致
- **`<b>` 目标词校验**：句子中 `<b>` 包裹的词必须是当前卡片的生词。若同一句中还出现了本牌组其他生词（如 `baobabs`），**绝不能**把 `<b>` 标到别的词上——生成后逐词确认 `<b>…</b>` 内的文本与 `word` 字段一致
- 例句应简洁：1-2 句，通常 ≤150 字符。**禁止**使用整段对话或长段落——仅提取目标词所在的核心句及其紧邻上下文，让学习者在 3 秒内定位到生词
- **以上规则由 `sync_anki.py` 在同步前自动校验**：句子长度 >150 字符、`<b>` 内容与 `word` 字段不匹配、必填字段（ipa/definition_cn/translation_cn）缺失均会拒绝同步并打印错误。尽早生成高质量内容，避免回滚重做

**翻译原则：**

> 准确、自然、可追溯。每个关键词汇在中文里要有对应，让学习者能从句子的中文字面反推出英文结构。不要逐字死译，也不要重新创作。

- **关键词映射可追溯**：`absence of reproaches` → "没有一句责备的话"（`absence`→"没有"、`reproaches`→"责备的话"），而不是"毫无责备之意"（丢失了 `absence` 的映射）
- **句式按中文习惯调整**：英文的代词、从句、被动语态大胆打破，换成中文流水句。但词义不走样
- **动词优先选用与英文义项直接对应的词**：`intimated` → "暗示"（而非"婉转地表示"），`linger` → "徘徊"（而非"流连"），确保学习者能根据中文反查英文原词
- **不要重新创作**：翻译的目的是辅助理解英文原句，不是独立的中文美文
- **多义词语境陷阱（common sense trap）**：英文中大量词汇有多个义项，不要自动选择最常见或最熟悉的义项。回到原文判断该词在此句中具体表达什么意思。例如 `thriftily` 在 "he must be treated thriftily" 中意为"有节制地，有所保留地"（sparingly, with restraint），而非"节俭地"（frugally, economically）——节俭适用于钱物，不适用于对人的"对待"。每次遇到不确定的词，先用中文问自己"这句话里这个词到底在说什么"，再选译义。若多个义项在中文中都说得通，优先选最能体现原文动作/状态特征的那个

**IPA 规则：**
- **IPA 必须对应 lemma（卡片展示词）**——卡片正面显示的是原形，音标应与卡片展示词一致。`lemma=blundering`→`/ˈblʌndərɪŋ/`；`lemma=ponder`→`/ˈpɒndər/`
- **必须为每个单词提供 IPA**——Claude 可从训练数据直接输出音标，无需外部 API
- 单词音频由 Edge TTS 默认发音生成（不使用 SSML `<phoneme>`——`edge_tts.Communicate` 内部对输入做 `escape()` 后再用 `mkssml()` 包一层 `<speak>`，外部 SSML 会被二次转义导致 TTS 朗读 XML 源码）
- IPA 缺失时跳过单词音频生成，卡片仍正常创建（例句音频正常生成）
- 对同形异音词（heteronym，如 `intimate` 形容词 /ˈɪntɪmət/ vs 动词 /ˈɪntɪmeɪt/），必须根据释义填入正确 IPA

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
4. **word 字段一致**：`word` 是否 = `<b>` 包裹的文本 = 句中出现的形式？
5. **语义情境对齐（多义词义项验证）**：对每个词，重读 sentence 中的上下文，确认 `definition_cn` 和 `translation_cn` 选择了该词在此句中的正确义项，而非其最常见词典义。执行以下验证：
   - **代入验证法**：将 `definition_cn`（去除"的/地/了"等标记）代入原英文句替换原词，看代入后的概念是否通顺合理。若替换后句子意思不通或产生逻辑矛盾，说明义项选错。例如 "he must be treated thriftily" → "节俭地对待他" 不通（对人不能"节俭"），说明应换义项
   - **义项枚举法**：脑中快速列出该词你知道的 2-3 个义项，逐一用代入验证法测试，选出最合理的一个
   - **跨句一致性检查**：若同一词在牌组中多次出现（不同句子），确认每个句子中该词的义项独立判断——前一句是"节俭"不意味着本句也是"节俭"
   - 发现定义/翻译与句子语境冲突时，修正后继续，不要遗留到下一批
6. **sentence-translation 对齐**：逐词检查 `sentence` 的英文语义单元，确认 `translation_cn` 中**每个中文语义元素在英文句中都有对应**。若翻译中出现英文句子里不存在的内容（如中文有「共同构成了我所收到礼物的光芒」但英文只有 `…the tenderness of smiling faces…`）→ 句子截断有误或翻译凭空添加。立即修正句子或同步裁切翻译，直到二者语义完全对齐

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
- **句子来源**：所有书的例句均通过 Step 3.0 从源文本机械提取，不再依赖 Claude 回忆。源文本不可用时回退到回忆模式，并在 Step 4 汇总中标明

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
- `ipa` 由 Claude 直接提供（训练数据），用于卡片显示；单词音频由 Edge TTS 默认发音生成；IPA 缺失时跳过单词音频
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
- **源文本校验状态**：已通过源文本校验的单词数 / 总数。回退到回忆模式的单词标 `⚠️`
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
4. **单词音频**：Edge TTS 默认发音（IPA 仅用于卡片显示）；IPA 缺失时跳过单词音频
5. **例句音频**：Edge TTS 朗读
6. **已有卡片完全不动**，保留复习进度和调度数据
7. **更新 meta manifest 卡片**：将本次 `excluded` 单词写入 Sentence 字段的 JSON manifest（`WordId = __META__{bookId}`），卡片暂停（不参与复习），下次同步优先读取
8. **触发 AnkiWeb 同步**：卡片添加完成后自动触发 `sync` 操作，将新卡片同步到 AnkiWeb。此操作为 fire-and-forget——成功响应仅表示 Anki 已接受请求，不代表 AnkiWeb 已收到数据。若 Anki 弹出冲突解决对话框，同步可能静默排队。使用 `--no-ankiweb-sync` 跳过此步骤

牌组名自动从 JSON 推导：`"{title} ({author})"`。额外参数：`--deck "自定义"`、`--dry-run`、`--no-audio`、`--no-ankiweb-sync`。

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
| 源文本不可用 | curl 直链 + WebSearch/WebFetch 均无法获取书中文本 → 回退到回忆模式，Step 4 汇总中标明「例句未校验」；若回忆也不确定，使用词典例句替代 |
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
| `coca_lookup.py` | COCA 20000 高频词查询 — 直接 set 查找 + lemminflect（仅接受原形严格短于输入词的映射，如 `pondered`→`ponder`；同长映射如 `abode`→`abide` 被拒，避免名词误映射到无关动词）+ 后缀剥离兜底做派生归一（`indulgently`→`indulgent`） | 单词 → set 查找 + lemminflect + 后缀剥离 | 是否在 COCA 前 20000 词中 |
| `coca_20000.txt` | COCA 20000 词表数据 | — | 17,640 个唯一 lemma |

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译、IPA），Python 做机械工作（HTTP、TTS、同步）。句子提取由 Step 3.0 源文本检索完成，不依赖 Claude 回忆
- **源文本检索替代回忆**：例句不再依赖 Claude 记忆生成，改为从网上拉取书中实际文本后机械匹配。Claude 的知识工作从「回忆句子+翻译+IPA」收窄为「翻译+IPA」，消除最易出错的环节
- **curl 优先于 WebFetch**：源文本拉取优先用 `curl -sL` 直链下载纯文本文件（Internet Archive、Project Gutenberg 等公版书站）。WebFetch 有严格引用字数限制（~125 字符/条），不适用于全书文本拉取，仅用作 curl 失败时的逐章兜底方案
- **章节优先匹配**：filter_pipeline.py 透传 WeRead 的 `chapterUid`/`chapterTitle` 到 JSON 输出，Step 3.0 优先在单词所属章节范围内搜索句子，避免同名异义词匹配到书中其他位置（如 `fair` 在"公平的"和"集市"两个义项间不会串章）。章节边界不确定时回退到全文本搜索
- **过滤前置**：Anki 去重和 COCA 频次检查在生成内容**之前**完成，避免浪费 Claude 精力。Anki 去重先于 COCA：已在牌组中的词不受 COCA 频次变化影响
- **音频并发**：多线程（16 workers）并发生成音频（Step 3.5），将音频生成压缩到秒级
- **确认前置音频**：音频在确认前预下载（`--prefetch`），确认后秒级同步（`--audio-dir`），用户不被阻塞
- **原形归一（三层分工）**：Step 1d `lemmatize_word()` 处理**屈折变化**（-ing/-ed/-s），用于去重。Step 1f COCA 的 `in_coca()` fallback 处理**派生归一**（`indulgently`→`indulgent`），用于频次匹配。Step 4 `sync_anki.py` 中 **spaCy 句子级校验**读原句判断 `-ed`/`-ing` 词的词性，阻止派生形容词被误还原（`distinguished` adj. 不退 `distinguish` v.）。三层互补，各司其职
  - 两层均使用 `len(lemma) < len(word)` 作为准入条件：同长映射（`abode` n.→`abide` v.）被拒，避免跨词性误判。不同长映射正常通过（`crammed`→`cram`、`went`→`go`）。同长不规则变化（`ran`→`run`、`sat`→`sit`）同为已知限制，但这些词属基础词汇，实际划线中极少出现
- **bookId 桥接**：Anki 卡片 WordId 天然包含 bookId（`{lemma}_{bookId}`），meta manifest 卡片格式固定（`__META__{bookId}`），用于精确关联微信读书，替代不可靠的书名匹配
- **一次性确认**：整个流程仅在最终同步前确认一次，中间步骤不打断
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范；Python 脚本间提取共享 `utils.py` 消除重复代码
- **故障降级**：音频获取失败不阻塞整体流程；同步超时有明确提示和建议
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响
- **IPA 零网络依赖**：Claude 从训练数据直接生成 IPA 用于卡片显示，无外部 IPA API 依赖。单词音频由 Edge TTS 默认发音生成（SSML `<phoneme>` 不可用——`edge_tts` 库内部二次转义导致 TTS 朗读 XML 源码）

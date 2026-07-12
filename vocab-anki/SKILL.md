---
name: vocab-anki
description: >
  Generate Anki vocabulary flashcard decks from WeRead (微信读书)
  English book highlights. Syncs directly to Anki via AnkiConnect plugin.
  Use when user wants to create Anki cards from WeRead highlights, e.g.
  "/vocab-anki The Little Prince" or "为这本书的划线生词生成 Anki 牌组".
  Integrates with weread-skills for data; Claude does knowledge work
  (sentences, definitions, IPA), DeepL handles translation, Python
  scripts handle audio + sync.
  For full-text vocabulary extraction, use vocab-book instead.
---

# vocab-anki — 英文书词汇 Anki 牌组生成

将微信读书英文原版书的划线生词（或全书词汇）通过 AnkiConnect 直接同步到 Anki，嵌入发音音频。
自动对比已有卡片，仅添加新词，保留学习进度不受影响。

## 模式

**仅划线模式** — 从微信读书英文原版书的划线生词制作 Anki 卡片。

> 如需从全书全文提取词汇（全文模式），请使用 `vocab-book` 技能。

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
> **确认策略：整个流程仅在 Step 2H（音频已预下载、同步/导出前）进行一次用户确认。其他步骤（含 Step 2G 音频预下载）仅输出进度，不询问。**
> **推迟同步：用户说"暂不同步"时，仅跳过 Step 2H（同步到 Anki）。Step 0b（AnkiConnect 检查）和 Step 1d（Anki 去重）仍正常执行——去重是过滤已有卡片，不属于同步。**

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
- 若有卡片 → 取一个 cardId → 通过 `cardsInfo` API 获取 `deckName`，形成映射表：
- **deckName 以 Anki `cardsInfo` 返回的实际值为准**（含大小写、重音符号），不得手动修改或根据 `book_title`/`book_author` 自行构造。

> **"暂不同步到 Anki"不影响 Step 0b**——去重需要查询 Anki 已有卡片，不查便无法知道哪些词是新的。仅当 Anki 真正不可达（如远程环境无法连接本地 Anki）时才跳过 Step 0b 和 Step 1d 的 Anki 去重。

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
    - **参数平铺**：业务参数（`keyword`）必须和 `api_name`、`skill_version` 放在 JSON 同一层，**不要包在 `params` 内**，否则网关不会转发参数。正确格式：
      ```bash
      curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
        -H "Authorization: Bearer $WEREAD_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"api_name":"/store/search","keyword":"老人与海","skill_version":"1.0.3"}'
      ```
  - 多版本时，并行检查英文版划线数量，标出划线最多的版本
  - `book_title` 和 `book_author` 必须为**纯英文**。微信读书对英文书的元数据
    常混入中文（如 title: `老人与海：The Old Man And The Sea（英文原版）`、
    author: `[美]海明威`），原样传入会导致牌组名混入中文。传递 `--book-title` /
    `--book-author` 给 `filter_pipeline.py` 之前必须清理：
    - **title**: 取英文部分（`：` 或 `:` 后的内容），去除 `（英文原版）`、
      `(English Edition)` 等中文/括号后缀，得到干净的英文书名
    - **author**: 去除 `[美]`/`[英]` 等国籍前缀；中文作者名转换为对应英文名
      （如 海明威→Ernest Hemingway, 简·奥斯汀→Jane Austen, 乔治·奥威尔→George Orwell）
    - **参考现有牌组**: 若 Step 0 匹配到同名书的任何现有牌组（含 vocab-book 分级牌组），
      以牌组名中解析的 title/author 为准，不要用 WeRead 原始返回值

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

> `filter_pipeline.py` 单次调用，脚本内部按序执行：
> 原形提取 → Anki 去重 → COCA 检查。
> **禁止 Claude 在 echo 中传递数据**——所有数据通过 stdin/stdout 在进程间流通。

**指定章节**：当用户要求特定章节（如"第 2 章"）时，在管道传入 `filter_pipeline.py` 之前从 WeRead API 响应中预过滤 `updated[]` 数组。匹配 `chapterUid` 并保留完整 `chapters[]` 数组：

```bash
# 先查 chapters[] 找目标章节的 chapterUid，再过滤
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/book/bookmarklist","bookId":"<bookId>","skill_version":"1.0.3"}' | \
python3 -c "
import json,sys; d=json.load(sys.stdin)
target_ch = [c for c in d['chapters'] if 'Chapter <N>' in c['title']]
# 找到 chapterUid: target_ch[0]['chapterUid']
d['updated']=[h for h in d['updated'] if h['chapterUid']==<chapterUid>]
json.dump(d,sys.stdout)
" | <skill_dir>/.venv/bin/python3 <skill_dir>/filter_pipeline.py ...
```

> **Warning**: Do NOT use `2>&1` in this pipe — it merges stderr into stdout, breaking JSON parsing in `filter_pipeline.py`. The inline Python script writes only JSON to stdout; `print(..., file=sys.stderr)` output stays on stderr and does not interfere with the pipe.

在 Step 2A 中，使用**全文源文本**进行句子匹配，不要用 `--start-offset`/`--end-offset` 限制范围。

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
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_pipeline.py \
	  --anki-dedup same-book --book-id <bookId> \
	  --book-title "<Book Title>" --book-author "<Author Name>" \
	  --json-out /tmp/vocab-anki-filtered-<bookId>.json
```

- `--anki-dedup same-book`：启用同书 Anki 去重（查已有卡片）；若 Step 0b 确认全库 0 张 Vocabulary Card 笔记，可省略此 flag 跳过 Anki 查询。**注意**："暂不同步到 Anki"不是省略此 flag 的理由——去重是过滤步骤，不属于同步。仅当 Anki 真正不可达时才跳过
- `--book-id <bookId>`：bookId 标识，用于 WordId 构建 + 同书去重目标
- `--book-title` / `--book-author`：书籍元数据，用于自动推导牌组名（从 Step 1 WeRead API 获取）
- `--json-out <path>`：将过滤结果写入结构化 JSON 文件，供 Step 2B/2E Claude 读取填充 `excluded` 数组，避免手动转录

输出分为四段：`SUMMARY:` 行、`---IN_COCA---` 表、`---EXCLUDED---` 表、`---ANKI_SKIPPED---` 表（Anki 已有卡片，仅当存在时出现）。同时写入对应的结构化 JSON 到 `--json-out` 路径。

JSON 输出中 `in_coca[]` 每项含 `chapters` 和 `coca_level` 字段：
```json
{
  "lemma": "abruptly",
  "rep": "abruptly",
  "forms": ["abruptly", "abruptly"],
  "coca_level": 5,
  "chapters": [
    {"chapterUid": 96, "chapterTitle": "Chapter 3"},
    {"chapterUid": 98, "chapterTitle": "Chapter 5"}
  ]
}
```
- `coca_level`：该词在 Nation BNC/COCA 词族中的等级（1-25），供 `sync_anki.py` 自动频次分级使用
- `chapters`：该词所有出现的章节列表（按 `chapterUid` 升序）；词在多个章节被划线时含多个条目
- `chapterUid` 为 WeRead 内部章节 ID，`chapterTitle` 为章节标题（如 "Chapter 10"）
- `chapters` 为参考信息，供 Step 2A 手动定位时查看该词出现的章节

> **Claude 注意**：若输出 `SUMMARY: 0 highlights → 0 lemmas`，在判定"没有划线"之前先用 `head -c 500` 查看原始 API 响应，确认 `updated` 字段确实存在且为空数组，排除 API 调用失败。

**Step 1 汇总（仅数字，不确认）：**

> 一步完成，中间不暂停、不询问用户。

```
划线 X 条 → 原形去重 Y 个 → Anki 已有 A 个, 历史排除 M 个 → 新增 COCA 排除 B 个 → 待生成内容 C 个
```

> Anki 去重先于 COCA：已在牌组中的词直接保留，不受 COCA 频次影响。COCA 仅对真正的新词做筛。所有检查均为本地/本地网络查询（~0.5s），无需缓存。

## 共享工作流（Step 2A–2H）

> Steps 2A（句子匹配 + POS 分析 + lemma + IPA + smart_truncate 自动截断）、2B（完整性校验，不可绕过）、2C（DeepL 翻译）、2E（生成释义，不碰 lemma）、2F（内容验证，不可绕过）、2G（预下载音频）、2H（确认+同步）与 vocab-book 共享。
> **详见 `<skill_dir>/lib/SHARED_WORKFLOW.md`**——Claude 执行到对应步骤时必须 Read 该文件获取完整指令。

共享步骤中关键脚本（`<skill_dir>/lib/` 前缀）：
- `lib/scripts/match_sentences.py` — 句子匹配 + per-sentence spaCy POS 分析 + (lemma,pos) 分组 + cmudict IPA + 碎片自动合并 + `smart_truncate()` 自动截断
- `lib/scripts/translate_deepl.py` — DeepL 翻译（Step 2C）
- `lib/sync_anki.py` — 音频预下载 + 同步脚本。此脚本使用相对导入，仅能以模块方式运行：`cd <skill_dir> && .venv/bin/python -m lib.sync_anki <args>`。同步时根据 `target_offset` 拼接 `<b>` 标签。去重时打印丢弃条目详情
- `lib/scripts/audit_deck.py` — 同步后审计
- `lib/scripts/check_step_completed.py` — 步骤完成检查点（支持 `--step 2B`, `--step 2B-verify`, `--step 2E`, `--step 2F`, `--step 2F-dup`, `--step all`）

**划线模式特有调整**：
- `<tmp_id>` 使用微信读书 `bookId`
- WordId = `{lemma}_{pos}_{bookId}`，音频文件 = `{lemma}_{pos}_{bookId}_word.mp3` / `_sent.mp3`
- 句子匹配使用全文源文本，不做章节范围限制
- Anki 去重已在 Step 1d 完成；`sync_anki.py` 另在音频生成前执行批内 WordId 去重
- 牌组名：`{English Title} ({Author})`（无分级后缀）

## 异常处理

划线模式特有：

| 情况 | 处理 |
|------|------|
| 没有划线 | (1) Step 1d 报错退出 → API 响应无效，检查 `$WEREAD_API_KEY`、bookId 后重试；(2) 正常输出 `SUMMARY: 0 highlights` → 提示用户在微信读书中标记生词后再试 |
| 划线全是整句 | 提示："划线看起来是完整句子而非生词。仍然可以生成牌组，是否继续？" |
| `WEREAD_API_KEY` 未设置 | 提示用户设置：`export WEREAD_API_KEY=<your-key>` |
| 没有新划线生词 | 直接告知用户「没有新的划线生词」，流程自动结束 |

共享异常处理（源文本不可用、音频失败、AnkiConnect 不可达等）参见 `<skill_dir>/lib/SHARED_WORKFLOW.md`。

## 输出

- 打印新增/跳过的单词数量
- 用户直接在 Anki 中看到新卡片出现
- 复习进度完整的牌组不受影响

## 脚本清单

| 脚本 | 用途 |
|------|------|
| `filter_pipeline.py` | 合并过滤流水线 — 标点/大小写清理 → lemmatize → Anki 去重 → COCA 检查 |
| `lib/sync_anki.py` | 增量同步到 Anki — 信任 JSON lemma，`target_offset` 拼接 `<b>` 标签 |
| `lib/ankiconnect.py` | AnkiConnect 客户端模块 |
| `lib/utils.py` | 共享工具 — lemmatize_word, edge_tts_bytes/file, safe_filename, validate_plain_text |
| `lib/coca.py` | BNC/COCA 词族等级查询（Nation 2017）|
| `lib/scripts/match_sentences.py` | 句子匹配 + POS 分析 + lemma + IPA（支持 `--start-offset` / `--end-offset` 限定范围）|
| `lib/scripts/translate_deepl.py` | DeepL 翻译 |
| `lib/scripts/extract_chapter.py` | 章节边界检测 + 提取（支持 `--boundaries-file` 外部边界）|
| `lib/scripts/audit_deck.py` | 牌组质量审计 |
| `lib/scripts/check_step_completed.py` | 步骤完成检查点 |
| `lib/chapter_detect.py` | 章节边界检测（共享模块） |
| `lib/validation.py` | 词条格式验证 |
| `lib/data/bnc_coca/` | BNC/COCA 词族数据 |
| `tests/` | pytest 单元测试套件 |

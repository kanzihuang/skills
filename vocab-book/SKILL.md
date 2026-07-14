---
name: vocab-book
description: >
  Extract vocabulary from any English book's full text, generate Anki
  flashcard decks with BNC/COCA frequency banding via AnkiConnect.
  Does NOT require WeRead (微信读书). Use when user says "全文制作",
  "全量词汇", "按词族等级", "词频范围", "全文", "vocabulary from
  entire book", "all words from this book", or specifies a book
  text file/URL directly. Claude handles knowledge work (sentences,
  definitions, IPA), DeepL handles translation, Python scripts handle
  filtering, audio, and sync.
---

# vocab-book — 英文书全文词汇 Anki 牌组生成

从任意英文书全文提取词汇，按 BNC/COCA 词族等级（Nation 2017）自动分级为层级牌组，
通过 AnkiConnect 同步到 Anki，嵌入发音音频。**不依赖微信读书。**

## 与 vocab-anki 的区别

| | vocab-anki | vocab-book |
|---|---|---|
| 数据源 | 微信读书划线 | 全书文本（文件/URL） |
| 依赖 | weread-skills + WEREAD_API_KEY | 无外部依赖 |
| 范围 | 已划线词汇 | 全量词汇 |
| 频次分级 | 单层牌组 | 自动 COCA 分级层级牌组 |
| 章节选择 | 可选（extract_chapter.py） | 无 |
| Anki 去重 | 同书去重 | 父牌组级别去重（UUID 复用 + 跨子牌组查询） |

## 前置条件

- Python 3 + venv（脚本自动创建并安装依赖）
- Anki 正在运行 + [AnkiConnect 插件](https://ankiweb.net/shared/info/2055492159) 已安装
- 书籍文本文件（用户提供路径 / 可下载的 URL）

> **云主机/远程环境**：若 Claude Code 在远程而 Anki 在本地，需 SSH 反向隧道：
> ```bash
> ssh -R 8765:localhost:8765 user@remote-host
> ```
>
> **确认策略**：整个流程仅在 Step 2H（音频已预下载、同步/导出前）进行一次用户确认。其他步骤（含 Step 2G 音频预下载）仅输出进度，不询问。Step 2G 必须在等待用户确认前完成——用户确认后 Step 2H 直接从缓存加载音频，秒级同步。
> **推迟同步**：用户说"暂不同步"时，仅跳过 Step 2H（同步到 Anki）。Step 2A-post（Anki 去重）仍正常执行——去重是过滤已有卡片，不属于同步。

## 工作流

### Step 0: 确认需求 + 检测已有 UUID

> ⚠️ **不可绕过（MUST）**。不执行此步骤会导致 Anki 去重完全失效——
> 新生成的 UUID 与已有卡片不匹配，`dedup_anki.py` 始终返回 "0 in deck"，
> 所有卡片被当作新词重新生成。参见 [[vocab-book-step-0-mandatory]]。

1. 确认 BNC/COCA 词族等级范围（用户未指定时提问）。
2. 检测 Anki 中是否已有该书的牌组，如有则提取 UUID suffix 供复用：

```bash
python3 -c "
from lib.ankiconnect import AnkiConnect
ac = AnkiConnect()
deck, suffix = ac.find_vocab_book_suffix('Title', 'Author')
if suffix:
    print(f'SUFFIX={suffix}')
    print(f'DECK={deck}')
else:
    print('SUFFIX=')
"
```

若 Anki 未运行则跳过（降级为生成新 UUID）。

COCA 范围意图解析：

| 用户表达 | 解析结果 | `--basic-range` |
|----------|---------|-----------------|
| "等级 3-10" | Level 3-10，一个牌组 COCA 3-10 | `3-10`（双边） |
| "等级 3-5,6-8,9-12" | 三个牌组 | `3-5,6-8,9-12`（多组双边） |
| "等级 8 和 9" / "等级 5,7,10" / "Coca 7, 8, 9" | 多个独立等级，各为一个牌组 | `7,8,9`（逗号分隔独立等级） |
| "排除前3级" | 排除 Level 1-3 | `4`（仅下限，默认分组） |
| "5级以上" | Level 5-25 | `5`（仅下限，默认分组） |
| "COCA 3000+" | 排除 Level 1-3（前 3000 词） | `4`（仅下限） |
| "中频词" / "中等难度" | 大致 Level 4-10 | **提问确认具体范围** |
| 未提及 | 无范围限制，默认分组 | 省略 `--basic-range` |

> 1-based level: level 1 = 最高频。两端均 inclusive。
> **双边规则**：指定 lo 和 hi（如 `3-10`）→ 牌组名 = `COCA 3-10`。
> **独立等级**：逗号分隔多个裸数字（如 `8,9`）→ 每个等级独立为子牌组（`COCA 8` + `COCA 9`）。仅当全部为裸数字时生效；混用 `-` 范围（如 `3-5,8`）会报错。
> **单边/未指定**：默认分组 COCA 1-3 / 4-6 / 7-9 / 10。
> 逗号分隔多组双边时，每组独立为一个子牌组。
> ⚠️ **反模式**：用户说 "Coca 7, 8, 9"（逗号分隔列表）≠ "Coca 7-9"（合并范围）。**永远不要**将逗号分隔的等级列表自行合并为 `-` 范围 —— 这会产生错误的牌组结构（一个合并牌组而非三个独立牌组）。

全文模式**默认全书统一处理**。用户指定章节时可用 `extract_chapter.py` 裁剪文本。`match_sentences.py` 自动检测并跳过序言和尾页（前言/作者简介/书目列表/版权声明/献词/生产者信息等非正文内容）——检测的是文本结构边界，不依赖逐词章节归属。
Anki 去重**不做**——每次运行独立，UUID 后缀确保不与其他牌组冲突。

### Step 1: 获取书籍文本

优先使用用户直接提供的文件路径。若无，WebSearch 书名+full text 查找公版书：

```bash
# 用户直接提供文件
cp /path/to/book.txt /tmp/<safe_title>-$(python3 -c "import uuid;print(uuid.uuid4().hex[:8])")-full.txt

# 或 curl 下载
curl -sL --max-time 60 '<URL>' -o /tmp/<safe_title>-$(python3 -c "import uuid;print(uuid.uuid4().hex[:8])")-full.txt
# 验证：必须是英文原版，不含双语对照/非英文元数据
head -c 500 /tmp/<safe_title>-*-full.txt
```

> 文件 >20KB 且包含书中实际文本。**必须使用英文原版**——双语版中的中文翻译、西里尔字母、guillemet（«»）等非英文内容会污染句子匹配。`match_sentences.py` 遇到此类文本直接拒绝。优先选择 Project Gutenberg（英文版）、Standard Ebooks、Internet Archive 英文原版。**不要使用 ESL 简化版或双语对照版替代**——改写后的句子与原文不符。

拉取后做质量验证（`head -c 500`）：
- **纯文本格式验证**：`head -c 100 <file> | grep -q '<html\|<!DOCTYPE'` → 则文件为 HTML 包装，需换源获取纯文本版本
  - Internet Archive：必须使用 `/download/` 路径（文件直链），而非 `/stream/`（HTML 阅读器页面）。即使 URL 以 `_djvu.txt` 结尾，`/stream/` 也会返回 HTML。URL 格式：`https://archive.org/download/<id>/<filename>_djvu.txt`，其中 `<id>` 取自 details 页 URL（`archive.org/details/<id>`），`<filename>` 取自该页下载选项中的 txt 文件名
- 正文句子是否完整（非章节摘要片段）
- 有无明显 OCR 损坏（如 `fig ures` → 字母间多余空格）
- 首句是否与公认经典译本一致（排除 ESL 简化版/改编版/双语版）
- 有问题 → 换源重新拉取，不要用损坏文本

**章节提取（用户指定章节时）**：

```bash
# 列出所有检测到的章节
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/extract_chapter.py /tmp/<safe_title>-*-full.txt --list

# 提取第 N 章到裁剪文件
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/extract_chapter.py /tmp/<safe_title>-*-full.txt --chapter <N> --output /tmp/<safe_title>-ch<N>.txt
```

提取后的文本自动排除序言（章节提取从章节标题开始）。后续步骤使用裁剪后的文件。未检测到章节标题时打印警告，使用原始全文本。

> **注意**：`match_sentences.py`（Step 2A）默认在全文本范围内搜索例句。如果只提取了单章节词汇，必须将裁剪后的章节文件作为 `source_text` 传入 `match_sentences.py`，而非原始全文文件。否则词汇会被匹配到其他章节的句子。详见 `lib/SHARED_WORKFLOW.md` Step 2A-c 的「章节范围限定」说明。

**无章节标题的书籍**（如《小王子》Katherine Woods 译本无 CHAPTER I 等标记）：

Claude 阅读全文后根据语义识别章节边界，创建 JSON 边界文件传入 `--boundaries-file`：

```bash
# Claude 先识别章节边界，写入 JSON（start inclusive, end exclusive）
cat > /tmp/<safe_title>-boundaries.json << 'EOF'
[
  {"chapter": 1, "start": 0, "end": 6974},
  {"chapter": 2, "start": 6974, "end": 12345}
]
EOF

# 用边界文件列出章节
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/extract_chapter.py \
  /tmp/<safe_title>-*-full.txt \
  --boundaries-file /tmp/<safe_title>-boundaries.json --list

# 提取第 N 章
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/extract_chapter.py \
  /tmp/<safe_title>-*-full.txt \
  --chapter <N> --boundaries-file /tmp/<safe_title>-boundaries.json \
  --output /tmp/<safe_title>-ch<N>.txt
```

`--boundaries-file` 传入后跳过机械章节检测，直接使用外部边界。`--chapter N` 在 `--boundaries-file` 模式下按 JSON 中 `"chapter"` **字段**匹配（非数组位置）——例如 `{"chapter": 4, ...}` 用 `--chapter 4` 即可提取，无需用 `--chapter 1`。`--list` 预览确认边界准确后再提取。

### Step 2: 运行 filter_fulltext.py

> ⚠️ **必须先完成 Step 0**：若 Step 0 检测到已有 suffix，必须通过
> `--suffix` 传入。使用新 suffix 会导致 Anki 去重完全失效——
> WordId = `{lemma}_{pos}_{suffix}`，suffix 不同则无法匹配已有卡片。

```bash
# 确保 venv 存在
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 提取 + 过滤全文词汇（缓存文件路径已记录在记忆中，可直接 cat）
# --basic-range 支持:
#   - 双边: 3-10 → 一个牌组 "COCA 3-10"
#   - 多组双边: 3-5,6-8,9-10 → 三个牌组
#   - 独立等级: 8,9 → 两个单级牌组 "COCA 8" + "COCA 9"
#   - 多个独立等级: 7,8,9 → 三个单级牌组 "COCA 7" + "COCA 8" + "COCA 9"
#   - 单边/省略: 默认分组 COCA 1-3, 4-6, 7-9, 10
# --suffix: ⚠️ 必须传入 Step 0 检测到的 UUID！不传则生成新 UUID，Anki 去重失效
cat /tmp/<safe_title>-*-full.txt | \
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_fulltext.py \
  --basic-range 3-10 \
  --suffix <reused-uuid> \
  --book-title "Book Title" --book-author "Author Name" \
  --json-out /tmp/vocab-book-filtered.json
```

> **`--book-title` / `--book-author` 必须为纯英文**。书名和作者名会用于自动推导
> 牌组名 `{title} ({author}) - 分级词汇`，混入中文会导致牌组名异常。

脚本内流水线：
1. spaCy 健康检查：验证 spaCy + `en_core_web_sm` 可用，失败自动修复
2. 分词去重：spaCy tokenization → 唯一 surface form 集合
3. `in_coca(surface)`：直接查 surface form 是否在 BNC/COCA 25000 词族中
4. COCA 范围过滤 + 等级标注（`coca_level`: 1-25）
5. 生成 UUID 后缀（`uuid.uuid4().hex[:12]`），写入 JSON `suffix` 字段
6. JSON 输出（含 `in_coca[]`、`excluded[]`、`suffix`、`summary`）

不做 lemmatization——最终 lemma 由 `match_sentences.py` 从具体例句判定。

### Steps 2A–2H: 句子匹配 / 内容生成 / 翻译 / 音频 / 同步

> 以下步骤与 vocab-anki 共享。详见 `<skill_dir>/lib/SHARED_WORKFLOW.md`。

关键路径（`<skill_dir>` 内 `lib/` 前缀）：
- `<skill_dir>/lib/scripts/match_sentences.py` — 句子匹配 + per-sentence spaCy POS 分析 + (lemma,pos) 分组 + cmudict IPA + 碎片自动合并 + `smart_truncate()` 自动截断（Step 2A，一站式机械分析）
- **Step 2A-post**: Anki 去重 — `match_sentences.py` 产出后立即以 `(sentence, word)` 键机械去重，标记 `_already_in_anki`（见 `SHARED_WORKFLOW.md` Step 2A-post）
- **Step 2B**: Claude 审核截断结果 + 拒绝碎片句 + OCR 标点修正（1 agent，**不可绕过**，`smart_truncate()` 已在 Step 2A 中完成，目标词由 `target_offset` 定位）
- `<skill_dir>/lib/scripts/translate_deepl.py` — DeepL 翻译（Step 2C）
- **Step 2E**: 生成释义 + 补 cmudict 未覆盖 IPA + 异读词投票（Claude，N agents 并行，≤25 词/agent，**不碰 lemma**）
- **Step 2F**: 内容验证 — POS 对齐 + 释义准确 + 翻译一致性（Claude，1 agent，**不可绕过**）
- **Step 2F.5**: 重复检测 — Step 2F 的 POS 修正可能产生 `(lemma, pos)` 碰撞，在进入 Step 2G 前运行检查（见 `SHARED_WORKFLOW.md` Step 2F.5）
- `<skill_dir>/lib/sync_anki.py` — 音频预下载 + 同步脚本（Step 2G + Step 2H）。此脚本使用相对导入，仅能以模块方式运行：`cd <skill_dir> && .venv/bin/python -m lib.sync_anki <args>`。同步时根据 `target_offset` 拼接 `<b>` 标签。prefetch 模式（Step 2G）会跳过 `_already_in_anki` 标记的已知词汇，仅生成新词音频

**全文模式特有**：
- `<tmp_id>` 使用 JSON 中的 `suffix` 字段（而非 bookId）
- WordId = `{safe_filename(lemma)}_{pos}_{suffix}`；音频命名 = `{safe_filename(lemma)}_{pos}_{suffix}_word.mp3` / `_sent.mp3`
- 同步时按 COCA 分级创建层级子牌组
- **父牌组去重**：查询父牌组下全部子牌组，复用 UUID 跨批去重
- 卡片新增 `CocaLevel` 隐藏字段（不在模板显示），用于自动迁移错位卡片
- **牌组名由脚本自动生成**：父牌组 `{book_title} ({book_author}) - 分级词汇`，子牌组 `COCA {lo}-{hi}`（Anki 原生显示卡片数量）。Claude 不要设置 `deck_name` 字段，也不要传 `--deck` 参数

## 异常处理

| 情况 | 处理 |
|------|------|
| 无法获取全文 | 告知用户，建议提供文本文件 |
| 源文本不可用 | 该批次所有单词跳过，不生成卡片 |
| spaCy 不可用 | 自动修复（安装依赖+下载模型），修复失败则终止任务 |
| 脚本运行失败 | 检查依赖安装、网络连接 |
| 音频生成失败 | Edge TTS 重试 3 次后仍失败 → 抛 RuntimeError 阻塞同步 |
| AnkiConnect 不可达 | 自动重试一次（2s 延迟），仍失败则终止流程并打印排查指引（启动 Anki + 安装插件 + SSH 隧道） |
| 同步脚本超时 | 提示原因，建议重试 |
| 没有通过 COCA 的单词 | 提示用户放宽范围或换书 |

## 输出

- 打印新增/跳过单词数量
- 用户直接在 Anki 中看到层级牌组和卡片

## 设计原则

- **零微信读书依赖**：不调用任何 WeRead API
- **UUID 复用跨批**：检测已有牌组的 UUID 后缀并在后续运行中复用，实现跨批去重
- **父牌组去重**：查询父牌组下所有子牌组，仅添加全新的词
- **机械去重前置**：Step 2A 产出后立即以 `(sentence, word)` 键连接 Anki 机械去重（`dedup_anki.py`），标记 `_already_in_anki`。不依赖 POS/lemma，跨次运行稳定。Claude 工作和音频生成均跳过已存在卡片
- **卡片迁移**：词频等级变更时，自动将卡片移动到正确子牌组，保留复习进度
- **稳定子牌组名**：子牌组名不含单词数量（如 `COCA 4`）。Anki 原生在牌组列表中显示卡片数，牌组名保持稳定
- **per-sentence POS 独立**：每句话的词性仅根据该句内信号独立判定。禁止跨句词性推断——同一个词可以在不同语境中有不同词性。`compound` 依存无可靠句内信号区分形容词修饰语与定语名词，compound 相关词性歧义交由 Claude Step 2B/2F 审查
- **序言自动过滤**：`match_sentences.py` 自动跳过前言
- **Claude + Python 分离**：Claude 做知识工作（释义、句子审核），Python 做机械工作（POS、lemma、TTS、同步、过滤、IPA、截断、碎片合并）
- **例句来自源文本机械匹配**：不依赖 Claude 记忆
- **质量门禁不可绕过**：Step 2B（Claude 审核）和 Step 2F（内容验证）无 SKIP 条件。`smart_truncate()` 已在 Step 2A（match_sentences.py）中自动完成
- **碎片自动合并**：`split_sentences()` 自动检测并合并被源文本空行切分的相邻碎片句
- **截断后验证**：`check_step_completed.py --step 2B-verify` 验证 target_offset 正确；`--step 2F-dup` 检测 POS 修复产生的重复
- **AnkiConnect 快速失败**：所有 AnkiConnect 调用自动重试一次（2s 延迟）。`sync_anki.py` 在音频生成前执行预检（`version` ping），不可达则立即终止

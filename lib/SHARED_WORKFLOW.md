# 共享工作流 — 句子匹配 / 内容生成 / DeepL 翻译 / 音频 / 同步

> 本文档供 `vocab-anki`（划线模式）和 `vocab-book`（全文模式）共用。
> `<skill_dir>` 为当前技能目录（`vocab-anki/` 或 `vocab-book/`）。
> `<tmp_id>` 为临时文件标识（划线模式用 `bookId`，全文模式用 `suffix`）。

## Step 2A: 获取源文本 + 句子匹配 + POS 分析 + lemma + IPA

`match_sentences.py` 完成所有机械分析：源文本搜索、句子提取、spaCy POS 判定、lemma 产出、cmudict IPA。

### 2A-0. 检查缓存源文本（优先）

**每次执行 Step 2A 前，先查记忆中是否已记录该书的缓存路径。**

- 记忆命中 → 验证文件存在 → 验证文件名匹配 `*-<8位hex>-full.txt` 格式（uuid8 = `[0-9a-f]{8}`，与 SKILL.md Step 1 命名规范一致）→ **验证内容是否为 HTML**（`head -c 100 <file> | grep -q '<html\|<!DOCTYPE'` → HTML 检测到 → 当作 cache miss，重新按规范下载并更新记忆）→ 纯文本验证通过 → 使用缓存，跳过 2A-a/b
- 记忆命中但文件缺失（如 /tmp 被清理）→ 当作 cache miss，继续 2A-a/b 搜索下载
- 记忆命中但文件名不匹配规范（如旧格式 `tlp-full.txt` 无 uuid）→ 当作 cache miss，重新按规范下载并更新记忆
- 未命中 → 继续搜索

### 2A-a/b. 搜索并拉取源文本

WebSearch → curl 直链 → WebFetch 兜底。优先 Internet Archive / Project Gutenberg。验证英文原版。

拉取后做质量验证（`head -c 500`）：
- **纯文本格式验证**：`head -c 100 <file> | grep -q '<html\|<!DOCTYPE'` → 则文件为 HTML 包装，需换源获取纯文本版本（Internet Archive URL 规则详见 SKILL.md Step 1 纯文本格式验证说明）
- 正文句子是否完整（非章节摘要片段）
- 有无明显 OCR 损坏（如 `fig ures` → 字母间多余空格）
- 首句是否与公认经典译本一致（排除 ESL 简化版/改编版/双语版）
- **标点质量**：检查是否有异常的冒号滥用（冒号误代句号是常见 OCR 错误）、连写字（"th e"）、双重空格
- 有问题 → 换源重新拉取，不要用损坏文本

### 2A-c. match_sentences.py — 全量候选 + POS 分组 + lemma + IPA

```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/match_sentences.py \
  /tmp/vocab-anki-input-<tmp_id>.json \
  <source_text_path> \
  --json-out /tmp/vocab-anki-input-<tmp_id>.json
```

脚本流水线（全书扫一次，句子为外循环）：

0. 源文本预处理：
   - `_normalize_quotes()` — Unicode 弯引号（`""''`）→ ASCII 直引号，避免传播到 JSON 输出
   - `_normalize_dialogue_attribution()` 合并 `[:,]\n\n"` → `\1 "`（对话引语与上文连成整句）
1. PySBD 一次切句 + 篇章检测跳过序言
1a. 碎片合并：`_merge_adjacent_fragments()` 自动合并被源文本空行切分的相邻碎片句。单次遍历，每个片段先试后向合并（前句+当前片段，两者必须都是片段）再试前向合并（片段+小写续句，或片段+奇引号无条件前向）。通过 `build_sentence_regex()` 验证合并结果是源文本的连续子串
2. 建 `form_index`：`form_lower → [(idx, entry), ...]`
3. 遍历每个句子：
   a. 快速 pre-filter（简单 token 查 form_index）
   b. hard_truncate（>500 字符硬截断）
   c. `nlp(sentence)` — 每句只跑一次
   d. 遍历 doc tokens，查 form_index → `(idx, entry, token)`
      - 跳过连字符复合词片段：`dep=compound` 且与 head 间有 `-` 的 token（如 "mast-head" 中的 "mast"）被自动跳过，避免产生 POS 错误的重复卡片
   e. `_determine_lemma(token)` → lemma，PROPN→NOUN 覆盖
   f. `_better()` 增量比较 → 只保留每个 `(lemma, pos)` 的最佳句
4. 后处理：回填 `char_offset` + cmudict IPA

输出 JSON：每个 `(lemma, pos)` 一个 entry，含 `lemma/word/pos/dep/spacy_lemma/be_to/coca_level/sentence/target_offset/ipa`。句子**不含 `<b>` 标签**。无 `candidates` 数组。

#### 章节范围限定（全文模式中提取单章词汇）

从全文提取单个章节的词汇时，`match_sentences.py` 默认搜索全文本范围，导致跨章句子匹配（如第 4 章的词被匹配到第 8 章的句子）。提供两种方式限定匹配范围：

**方式 A：提取章节文本后作为 `source_text` 传入**（推荐，最简单）
```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/extract_chapter.py \
  /tmp/<safe_title>-<uuid8>-full.txt --chapter 4 --output /tmp/<safe_title>-ch4.txt

<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/match_sentences.py \
  /tmp/vocab-book-filtered.json /tmp/<safe_title>-ch4.txt
```

**方式 B：使用 `--start-offset` + `--end-offset` 限定字符范围**
```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/match_sentences.py \
  /tmp/vocab-book-filtered.json /tmp/<safe_title>-<uuid8>-full.txt \
  --start-offset 10322 --end-offset 14556
```
`--end-offset` 默认为全文结尾（向后兼容）。`_sentence_char_offset()` 仍搜索全文本以确保 `char_offset` 对应全文位置。

两种方式的区别：方式 A 将搜索范围完全限定在章节文本内；方式 B 的 `char_offset` 仍基于全书偏移（适合后续全文定位）。

> 对于无章节标题的书籍（如《小王子》Katherine Woods 译本），需使用 `--boundaries-file` 机制提取章节。详见 SKILL.md Step 1 的「无章节标题的书籍」小节。

### 2A-d. 版本校验 + 失败处理

源文本获取失败 → 该批次所有单词跳过。

**已知局限**: 当源文本在句中包含空行时（通常为 OCR 或排版 artifact），PySBD 会将其切为多个碎片。`_merge_adjacent_fragments()` 自动合并大多数碎片（双向合并 + 奇引号放松）。`_cleanup_unclosed_quote()` 在 `smart_truncate` 截断时通过前向搜索闭合引号保留对话归属句。两个修复协同大幅降低碎片率。无法自动合并的碎片仍由 `_is_fragment()` 标记（`is_fragment=True`），在 Step 2B 中直接拒绝该词（不修复）。

---

## Step 2B: 句子审核 + 完整性校验（Claude，1 agent）

> ⚠️ **不可绕过（MUST）**。

### 2B. 手动审核（Claude）

审核重点：
- ``_auto_truncated`` 标记的条目 — 确认截断位置语义合理
- 序言/非正文句子（`char_offset` 靠前、内容为作者简介/编辑导语）
- **语法不完整的句子片段** — ``is_fragment=True``、不以 ``. ! ?`` 结尾、小写开头 → **直接丢弃该词**（不修复）。碎片修复已被移除——空行碎片合并已在 ``match_sentences.py`` 中机械处理，无法自动合并的碎片不可靠，不应制成卡片
- **OCR 标点错误**：句尾 `:` 或 `,` 在语法完整的句子中实为 OCR 对句号的误识别
- 完整长句（``_auto_truncated`` 未标记但 > ``MAX_SENTENCE_LENGTH``）— 确认无法机械截断后接受

> **连字符复合词片段**（如 "mast-head" 中的 "mast"）已由 match_sentences.py
> Step 2A-3d 机械跳过，不再出现在输出中。此检查不再需要 Claude 人工处理。

**OCR 标点修正规则**：
- 检查句子末尾标点：若句尾为 `:` 或 `,` 且句子语法完整（有主语+谓语），且冒号/逗号后面的内容不是对话引语 → 可能是 OCR 对句号的误识别
- **修正方法**：将句尾 `:` 或 `,` 替换为 `.`。仅修改句子最后一个字符——不要修改句中任何标点
- 安全原因：此修改发生在 Step 2B（Claude 审查），先于 Step 2C（DeepL 翻译）和 Step 2F（验证）

**OCR 连字符空格修复**：Internet Archive 文本中常见连字符后有多余空格（如 `"fair-to- middling"`）。修正方法：移除连字符两侧多余空格 → `"fair-to-middling"`。此修正先于 DeepL 翻译。

**不完整句子的处理**：``match_sentences.py`` 自动合并了
大多数被源文本空行切分的相邻碎片。无法自动合并的句子会被标记
``is_fragment=True``。Step 2B 审查时遇到此类句子**直接丢弃该词**
——碎片修复不可靠，不值得制成卡片。``_merge_adjacent_fragments()``
已在 Step 2A 中了做了最大努力的机械修复。

### Step 2B.5: target_offset Verification (MUST run after Step 2B)

After Step 2B review, verify all ``target_offset`` values
still point to the correct word.  This catches off-by-one errors before
they reach Step 2H sync validation.

```bash
cd <skill_dir> && .venv/bin/python3 \
  <skill_dir>/lib/scripts/check_step_completed.py \
  /tmp/vocab-anki-input-<tmp_id>.json --step 2B-verify
```

A ``check_step_completed.py --step all`` also runs this check
automatically.

---

## Step 2C: DeepL 翻译

例句翻译全部由 DeepL API 完成。在 2B 之后执行。

```bash
if [ -n "$DEEPL_API_KEY" ]; then
    <skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/translate_deepl.py \
      /tmp/vocab-anki-input-<tmp_id>.json \
      --source-text <source_text_path>
fi
```

自动去重、上下文支持。翻译写回 `translation_cn`。`DEEPL_API_KEY` 未设置时跳过。

---

## Step 2E: 生成内容（Claude，N agents 并行）

为每个词生成 `definition_cn` + 补 cmudict 未覆盖词的 IPA + 异读词投票。

**lemma 由 match_sentences.py 机械产出，Claude 不可修改。**

分批：≤25 词/agent。参考翻译生成释义，释义应与翻译语义一致。

### 批处理操作流程

当条目 >25 时，拆分为 ≤25 词/批次的 chunk 文件并行处理：

**1. 主 agent 拆分 JSON：**

```bash
cd <skill_dir>
.venv/bin/python3 -c "
import json, math
with open('/tmp/vocab-anki-input-<tmp_id>.json') as f:
    data = json.load(f)
words = data['words']
chunk_size = 25
for i in range(0, len(words), chunk_size):
    chunk = dict(data)
    chunk['words'] = words[i:i+chunk_size]
    with open(f'/tmp/vocab-anki-chunk-{i//chunk_size:02d}.json', 'w') as out:
        json.dump(chunk, out, ensure_ascii=False, indent=2)
print(f'Split {len(words)} words into {math.ceil(len(words)/chunk_size)} chunks')
"
```

**2. 启动并行 Agent：** 每 4-5 个 chunk 启动一个 Agent，
每个 Agent 处理其分配的 chunk 文件（Read → 生成 definition_cn + IPA → Write）。

> ⚠️ **JSON 格式要求**：Agent 写入 chunk 文件时必须使用 Python 的
> `json.dump(data, f, ensure_ascii=False, indent=2)`，**禁止使用 Write
> 工具直接写入 JSON**。所有 JSON 键和字符串值必须使用 ASCII 直引号
> (`"` U+0022)，严禁弯引号/智能引号（`"` `"` `'` `'`）。
> 弯引号会导致 `json.load()` 解析失败，整个合并步骤崩溃。

**3. 验证 chunk 文件（合并前）：**

```bash
cd <skill_dir>
for f in /tmp/vocab-anki-chunk-*.json; do
    .venv/bin/python3 -c "import json; json.load(open('$f'))" || {
        echo "FAILED: $f — JSON is broken. Re-run the agent for this chunk."; exit 1; }
done
echo "All chunk files valid"
```

**4. 合并结果：**

```bash
cd <skill_dir>
.venv/bin/python3 -c "
import json, glob, os
chunks = sorted(glob.glob('/tmp/vocab-anki-chunk-*.json'),
                key=lambda p: int(p.split('-chunk-')[1].split('.')[0]))
words = []
for path in chunks:
    with open(path) as f:
        words.extend(json.load(f)['words'])
    os.unlink(path)
with open('/tmp/vocab-anki-input-<tmp_id>.json') as f:
    data = json.load(f)
data['words'] = words
with open('/tmp/vocab-anki-input-<tmp_id>.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Merged {len(words)} words from {len(chunks)} chunks')
"
```

**5. 验证完整性：**

```bash
cd <skill_dir> && .venv/bin/python3 \
  <skill_dir>/lib/scripts/check_step_completed.py \
  /tmp/vocab-anki-input-<tmp_id>.json --step 2E
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `word` | 书中出现的表面词形，JSON 中始终为表面词形 |
| `lemma` | match_sentences.py 机械产出，Claude 不可修改 |
| `coca_level` | 从 filter 输出透传 |
| `sentence` | 书中含该词的完整句子，不含 `<b>` 标签，`target_offset` 定位目标词 |
| `ipa` | match_sentences.py 从 cmudict 填充；未覆盖词由 Claude 补充。**格式必须包含 `/` 分隔符**，如 `/sprɪɡ/`，不可写为裸 `sprɪɡ` |
| `definition_cn` | 格式 `[pos.] 释义`。pos 必须用英文缩写，**不可使用中文**（如 `[名]`/`[动]`）：NOUN→`[n.]`、VERB→`[v.]`、ADJ→`[adj.]`、ADV→`[adv.]`、ADP→`[prep.]`、PROPN→`[n.]` |
| `translation_cn` | DeepL 提供的中文翻译 |

### 例句规则

- 必须是书中真实句子，来自 Step 2A 机械匹配
- 简洁：1-2 句，通常 ≤500 字符
- `<b>` 标签由 sync_anki.py 在同步时根据 `target_offset` 拼接

---

## Step 2F: 内容验证（Claude，1 agent）

> ⚠️ **不可绕过（MUST）**。

POS 对齐 + 释义准确 + 翻译一致性。`lemma` 不在此步检查（match_sentences.py 机械产出，不可修改）。

| 检查 | 说明 |
|------|------|
| POS 对齐 | `[词性]` 标注与句中实际用法一致 |
| NOUN+compound 误标 | `dep=compound` 且 `pos=NOUN` → 检查是否实际起形容词作用（如 "virgin forest"）。连字符复合词片段（如 "mast-head" 中的 "mast"）已由 match_sentences.py 机械跳过，不会出现在输出中 |
| 释义准确 | 代入验证法 + 义项枚举 + 跨句一致性 |
| 翻译一致性 | `definition_cn` 与 `translation_cn` 语义对齐 |
| be+VBN+by 情感形容词 | 对 `pos=VERB` + `word` 以 `-ed` 结尾 + 句中存在 "be...-ed...by" 结构的条目，执行 "very + word" 测试（"very disheartened" ✓ → 形容词）。若判定为情感/状态形容词 → `pos`→`ADJ`、`lemma`→`word`（表面词形）、`definition_cn` 改为形容词释义 |
| `dep=dobj` 裸不定式 | `pos` 为 NOUN 或 ADJ 且 `dep=dobj` → 检查 head 是否为半情态动词（dare, need, help）或感知动词（see, hear, watch, feel, notice, observe）。若单词在句中作裸不定式 → `pos`→`VERB`，`definition_cn` 改为动词释义。详见 CLAUDE.md |

机械检查（word 匹配、IPA 格式、功能词结尾等）由 match_sentences.py 和 sync_anki.py 自动执行。

### 进入 Step 2G 前的必检清单

`sync_anki.py` 要求 JSON 中以下字段非空，缺失将 crash：

| 字段 | 检查 |
|------|------|
| `book_title` | 必须非空且为纯英文（用于自动推导牌组名，混入中文会导致牌组名异常） |
| `book_author` | 必须非空且为纯英文（同上） |
| `suffix` 或 `book_id` | 至少一个存在（用于 WordId/音频命名空间隔离） |
| `words` | 必须是非空数组 |

> **vocab-book**: `filter_fulltext.py --book-title "Title" --book-author "Author"` 可自动填充前两项。
> **vocab-anki**: `filter_pipeline.py --book-title "Title" --book-author "Author"` 可自动填充前两项；也可由 Step 1 的 WeRead API 响应中提取。

### Step 2F.5: Duplicate Check (run before Step 2G)

Step 2F POS fixes (especially be+VBN+by → ADJ) can create ``(lemma, pos)``
collisions.  Run duplicate detection to catch them before sync:

```bash
cd <skill_dir> && .venv/bin/python3 \
  <skill_dir>/lib/scripts/check_step_completed.py \
  /tmp/vocab-anki-input-<tmp_id>.json --step 2F-dup
```

If duplicates are found, merge the entries or adjust POS to avoid the
collision.  ``sync_anki.py`` will also print details of any entries it
drops at sync time.

---

## Step 2G: 预下载音频

```bash
cd <skill_dir> && .venv/bin/python -u -m lib.sync_anki \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --prefetch -v
```

音频命名：`{lemma}_{pos}_{<tmp_id>}_word.mp3` / `{lemma}_{pos}_{<tmp_id>}_sent.mp3`

---

## Step 2H: 最终确认 + 同步

展示汇总 → 用户确认 → 上传音频 → 添加卡片 → 触发 AnkiWeb 同步。

```bash
cd <skill_dir> && .venv/bin/python -u -m lib.sync_anki \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --audio-dir <AUDIO_DIR_FROM_STEP_2G> \
  -v
```

`<b>` 标签在 `build_note_entry()` 中根据 `target_offset` 拼接。

---

## 卡片格式

### 正面
```
┌──────────────────────────┐
│       astounded          │  ← 40px 粗体（lemma）
│ ─────────────────────── │
│  And I was astounded    │  ← 例句，<b> 包裹表面词形
│  to hear the little     │
│  fellow greet it...     │
└──────────────────────────┘
```

### 背面
```
┌──────────────────────────┐
│  IPA: /əˈstaʊndɪd/      │
│  释义: [adj.] 大吃一惊的  │
│  翻译: 当我听到小家伙...   │
│  🔊 word  🔊 sentence   │
└──────────────────────────┘
```

---

## JSON 格式

```json
{
  "book_title": "书名",
  "book_author": "作者",
  "deck_name": "牌组名",
  "book_id": "微信读书 bookId（划线模式；与 suffix 二选一）",
  "suffix": "UUID 后缀（全文模式；与 book_id 二选一）",
  "words": [
    {
      "lemma": "astounded",
      "word": "astounded",
      "forms": ["astounded"],
      "pos": "ADJ",
      "dep": "acomp",
      "spacy_lemma": "astounded",
      "be_to": true,
      "coca_level": 7,
      "sentence": "And I was astounded to hear the little fellow...",
      "target_offset": 10,
      "char_offset": 5477,
      "ipa": "/əˈstaʊndɪd/",
      "definition_cn": "[adj.] 大吃一惊的，震惊的",
      "translation_cn": "当我听到那个小家伙..."
    }
  ],
  "excluded": [...]
}
```

## 异常处理（共享）

| 情况 | 处理 |
|------|------|
| 源文本不可用 | 该批次所有单词跳过 |
| 音频生成失败 | Edge TTS 重试 3 次后抛 RuntimeError |
| AnkiConnect 不可达 | 提示启动 Anki |
| 同步超时 | 提示重试 |
| 没有新生词 | 直接告知用户 |

## 设计原则（共享）

- **职责分离**：Claude 做知识工作（句子审核、释义、IPA 补漏），DeepL 做机械翻译，Python 做机械工作（POS 分析、lemma、TTS、同步、cmudict IPA）
- **例句来自源文本机械匹配**：不依赖 Claude 记忆
- **per-sentence POS 分析**：spaCy 在具体句子上判定词性，不全局投票。lemma 由机械流程产出，Claude 不参与
- **表面词形严格匹配**：目标词形必须实际出现在句中
- **增量安全**：只添加不修改
- **批内词族去重**：同批内同 lemma+pos 合并
- **确认前置音频**：确认前预下载，确认后秒级同步
- **WordId 含 POS**：`{lemma}_{pos}_{suffix}` 防止同 lemma 不同 POS 碰撞

# 共享工作流 — 句子匹配 / 翻译 / 内容生成 / 音频 / 同步

> 本文档供 `vocab-anki`（划线模式）和 `vocab-book`（全文模式）共用。
> `<skill_dir>` 为当前技能目录（`vocab-anki/` 或 `vocab-book/`）。
> `<tmp_id>` 为临时文件标识（划线模式用 `bookId`，全文模式用 `suffix`）。

## Step 3.0: 获取源文本（句子检索替代回忆）

**核心改进**：回忆式例句生成不可靠。改为从网上拉取书中实际文本，机械匹配每个生词所在句子，彻底消除编造风险。

### 3.0a. 搜索源文本

WebSearch `<英文书名> full text` 或 `<英文书名> <作者> full text`。优先选 Internet Archive（`archive.org`）、Project Gutenberg、Standard Ebooks。搜索时留意可直链下载的纯文本 URL（`.txt` 结尾或 `/download/` 路径）。

**必须使用英文原版**——双语对照版中的非英文内容会污染句子匹配。`match_sentences.py` 遇到含西里尔字母或 guillemet（«»）的文本直接拒绝。

> **不要使用 ESL 简化版或双语对照版替代**——改写后的句子与原文不符。

### 3.0b. 拉取源文本（curl 优先，WebFetch 兜底）

```bash
curl -sL --max-time 60 '<URL>' -o /tmp/<book>-full.txt
wc -c /tmp/<book>-full.txt
```

- curl 成功（文件 >20KB）→ 直接用
- curl 返回 HTML → 试 Internet Archive `/download/` 路径
- 全部失败 → WebFetch 逐章拉取
- 验证：`head -c 500` 确认是英文原版书中文本，不含双语对照或非英文元数据
- 搜一句书中知名台词，与公认的经典译本比对。若首句或知名段落与已知译文不符（如《小王子》首句不是 "Once when I was six years old..." 而是 "ONCE WHEN I was six..." 这类简化改写），则为 ESL 版或改编版，不可用

### 3.0b-1. 源文本版本选择

**选对源文本版本是最有效的质量控制**——坏的源文本（OCR 扫描版、带章节导航的网页提取版）导致的句子污染无法通过机械规则批量修复，只能逐句人工修正。

**优先顺序**：
1. Project Gutenberg / Standard Ebooks 的校对版纯文本（`.txt`）
2. Internet Archive 的扫描版（可能含 OCR 错误，如 `fig ures` → `figures`）
3. 网页逐章提取版（可能含章节导航标题粘连正文，如 `the little prince makes the acquaintance of the snake When one wishes to...`）

**拉取后验证**：`head -c 500` 查看前几段，检查：
- 正文句子是否完整（有主语+谓语，非章节摘要片段）
- 有无明显 OCR 损坏（字母间多余空格、标点缺失）
- 首句是否与公认经典译本一致（排除 ESL 简化版/改编版/双语版）

源文本有问题 → 换源重新拉取，不要勉强用损坏的文本生成例句

### 3.0c. 句子匹配

对每个待生成单词，在源文本中搜索（大小写不敏感）→ 提取所在完整句子。

- **章节优先匹配**（划线模式）：从 JSON 的 `in_coca[].chapters` 获取章节信息，优先在章节范围内搜索
- 匹配到 → 用 `<b>` 包裹目标词
- 未匹配到 → 标记 `⚠️`，回退回忆模式
- **全文模式无章节信息** → 全文本搜索
- PySBD 对话引号伪影（`" "No,`）由 `_clean_quote_artifact()` 自动清理

### 3.0c-1. 句子匹配校验

- 目标词表面词形实际出现在匹配到的句子中（大小写不敏感）
- 若找不到 → 扩大搜索，仍找不到 → `⚠️ 未匹配`
- 绝不在未确认时将 `word` 字段设为句中不存在的词形

### 3.0c-2. 句子完整性检查

- 必须有主语 + 定式动词谓语，不能是名词短语片段
- 首字符必须是大写字母或引号
- 禁止将片段写入 `sentence` 字段

### 3.0c-3. 扩展策略

若初始匹配是片段 → 向外扩展到完整句子边界。此阶段**不做截断**——截断由 Step 3A（Claude）执行。

### 3.0d. 版本校验

搜一句书中知名台词确认版本。未匹配 → 版本可能不同，仍以源文本为准。

### 3.0e. 句子截断（已移至 Step 3A）

截断从 Python (`match_sentences.py`) 移至 Claude (Step 3A)。Python 只做 500 字符硬截断作为安全网；语义截断由 Step 3A 在语法边界执行，三阶段贪婪+回退策略，优先保证完整性。

源文本获取失败 → 该批次所有单词跳过。禁止回退词典例句。

## Step 3.0f: DeepL 翻译

在 **3A→3B→3C 完成之后**执行，翻译的是 3A 已确定的最终句子。

前置条件：`DEEPL_API_KEY` 环境变量。

```bash
if [ -n "$DEEPL_API_KEY" ]; then
    <skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/translate_deepl.py /tmp/vocab-anki-input-<tmp_id>.json
fi
```

脚本行为：
- 剥离 `<b>` 标签 → DeepL（`target_lang=ZH`）
- 每批 50 句，遇失败逐句重试
- 翻译写回 `translation_cn`
- 打印字符用量

若 DEEPL_API_KEY 未设置 → 跳过，翻译由 Claude 在 Step 3B 中完成。

## Step 3A: 句子选择 + 完整性校验（Claude，1 agent）

**在 3B 生成释义之前执行**，避免为会被排除的词浪费 3B 时间。

从 match_sentences.py 输出的 candidates 中为每个词选句、做语义完整性校验、仅极端长句做语义截断。

### 输入

- `candidates` 数组（含 `<b>` 标签，按原文出现顺序，≤5 句）
- `char_offset`（词在源文本中的字符位置）
- `source_text_path`（源文本路径）
- 书上下文（书名 + 2-3 句情节简介，由主流程启动 agent 时写入 prompt）

### 执行流程

```
对每个 word:
  for sent in candidates:
    1. 句子选择：
       - 仅 1 个 candidate → 直接选用（不做语义校验）
       - 多个 candidate → 选最短的完整句（PySBD 已保证句子边界）

    2. 极端长句判断（满足任一 → 语义截断）：
       a. 去标签后 > 250 字符
       b. 含 3+ 并列独立分句（`, and` / `, but` / `;` 连接）
       → 不满足 → 直接选用
       → 满足 → 三阶段语义截断：
         Phase 1 贪婪：从句末向句首，逐边界往前尝试，第一个完整句 → 选用
         Phase 2 硬停止：下一个边界越过 <b> 标签或主句主干 → 不再往前
         Phase 3 回退：回到 Phase 2 前的边界 → 句子长但完整 → 接受

    3. 截断后 C3 检查（仅对截断过的句子）：
       C3. 截断是否切掉了代词的先行词？
       → 是 → 回退到 Phase 3 边界（接受长句）
       → 否 → 选用截断后的句子

       注意：非截断句不做 C3 检查。对话中 "He said..." 的 He
       指前一句的主语是正常叙述，不算悬空。

  全部 candidate 失败 →
    4. 回源文本手动提取（Read source_text_path offset=char_offset±500）
       → 目视完整句边界 → 手动切出 → 跑步骤 1-3
    5. 仍然失败 → excluded
```

C3 仅检查截断引入的悬空指代——不确定就回退，宁长勿碎。

### 输出

为每个词确定 `sentence`（含 `<b>` 标签）或排除。

---

## Step 3B: 生成释义 + IPA（Claude，N agents 并行）

用 3A 确定的最终句子逐词生成 `definition_cn` 和 IPA。

**分批**：≤25 词/agent。≤30→1, 31–80→4, 81–200→8, 200+→10+。
**不自查**——自查职责移至 3C。

### 字段说明

| 字段 | 说明 |
|------|------|
| `word` | 表面词形（纯文本，不含 `<b>` 标签）。`<b>` 标签仅存在于 `sentence` 字段中 |
| `lemma` | 派生形容词必填，常规屈折留空 |
| `coca_level` | 从 filter 输出原样透传 |
| `sentence` | 含 `<b>…</b>` 的完整句子（3A 已确定） |
| `ipa` | cmudict 自动生成；多发音词时 Claude 投票 |
| `definition_cn` | 按句中实际用法释义 |
| `translation_cn` | DeepL 翻译（Step 3.0f，在 3C 之后执行） |

---

## Step 3C: 内容验证（Claude，1 agent）

POS 对齐 + 释义准确。仅校验 Claude 产出，不涉及翻译。发现问题 → 直接修正。

| 检查 | 说明 |
|------|------|
| POS 对齐 | def 词性 vs lemma 词性？ |
| 释义准确 | 代入验证法 + 义项枚举 |

机械检查（word=`<b>` 标签、IPA 格式、功能词结尾等）由 match_sentences.py 和 sync_anki.py 纵深防御执行，不在 3C。

### JSON 格式

```json
{
  "book_title": "书名",
  "book_author": "作者",
  "deck_name": "牌组名",
  "words": [
    {"word": "pondered", "lemma": "ponder", "coca_level": 3, "ipa": "/.../", "sentence": "...", "definition_cn": "...", "translation_cn": "..."}
  ],
  "excluded": [
    {"word": "abash", "reason": "不在 BNC/COCA 25000 词族中"}
  ]
}
```

> IPA 由 cmudict 自动生成；Claude 仅多发音词时提供投票。

## Step 3.5: 预下载音频

```bash
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

<skill_dir>/.venv/bin/python -u <skill_dir>/lib/sync_anki.py \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --prefetch -v
```

输出末尾 `AUDIO_DIR=<path>`，供 Step 4 使用。

## Step 4: 最终确认 + 同步

### 4a. 展示汇总

- 音频状态、本次新增单词（lemma）、源文本校验状态、lemma 覆写数量

### 4b. 空跑判定

本次新增为空且新增排除为空 →「没有新的生词」，终止。

### 4c. 确认

仅问一次：「确认同步？」

### 4d. 执行

```bash
WORD_COUNT=$(python3 -c "import json; print(len(json.load(open('/tmp/vocab-anki-input-<tmp_id>.json'))['words']))")
SYNC_TIMEOUT=$(( WORD_COUNT * 3 + 30 ))
[ "$SYNC_TIMEOUT" -lt 60 ] && SYNC_TIMEOUT=60

timeout $SYNC_TIMEOUT <skill_dir>/.venv/bin/python -u <skill_dir>/lib/sync_anki.py \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --audio-dir <AUDIO_DIR_FROM_STEP_3.5> \
  -v
```

### 同步详情（sync_anki.py）

1. `--prefetch`：并发生成音频 → manifest.json → `AUDIO_DIR=<path>`
2. `--audio-dir <dir>`：加载音频 → AnkiConnect → 查已有 → 上传 → 添加
3. 音频命名：`{lemma}_{suffix}_word.mp3` / `{lemma}_{suffix}_sent.mp3`
4. 已有卡片完全不动
5. 全文模式自动频次分级（`compute_bands()`）：COCA 级别 → 贪心分割 → 层级牌组
6. 触发 AnkiWeb 同步（fire-and-forget）

## 卡片格式

### 正面
```
┌──────────────────────────┐
│       pondered           │  ← 40px 粗体
│ ─────────────────────── │
│  I pondered deeply,     │  ← 例句，生词蓝色加粗
│  then, over the         │
│  adventures of the      │
│  jungle.                │
└──────────────────────────┘
```

### 背面
```
┌──────────────────────────┐
│  (正面内容重复)           │
│ ─────────────────────── │
│  IPA: /ˈpɒndər/         │
│  释义: 沉思，深思         │
│  翻译: 我于是对丛林中的    │
│  冒险深深思索起来。        │
│  🔊 word  🔊 sentence   │
└──────────────────────────┘
```

## 同步后审计（Step 4 完成）

逐张检查 Anki 卡片：
1. Word ≠ `<b>` 文本且不是合法原形还原
2. Word 被截断（`lavend`/`silv`/`weath` 等）
3. Word 大小写异常（`Amen`/`Champion`/`Dick` 等专有名词泄漏）
4. 翻译与例句语义一致（英文句子和中文翻译是否对应同一内容）
5. 例句来自英文原版书（不含西里尔字母、guillemet、章节号等非英文元数据——源文本在匹配阶段已拒绝非英文内容）

审计命令：
```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/audit_deck.py "牌组名"
```

### 自动校验（sync_anki.py 内置）

同步时自动执行以下检查（硬错误阻断同步，软警告打印到 stderr）：

| 类型 | 检查项 | 级别 |
|------|--------|------|
| 源文本 | 含西里尔/guillemet → 拒绝（要求英文原版） | 硬错误 |
| 句子 | `<b>` 标签与 word 字段一致 | 硬错误 |
| 句子 | 目标词实际出现在句中 | 硬错误 |
| 句子 | 长度 ≤250 字符（与 Step 3A 超长句触发条件一致） | 硬错误 |
| 句子 | 必需字段非空（ipa, definition_cn, translation_cn） | 硬错误 |
| 句子 | lemma 合理性（不应比 surface form 长） | 硬错误 |
| 句子 | 句尾功能词（介词/连词结尾） | 硬错误 |
| 句子 | 标点残留（`,.` `,)` 等） | 硬错误 |
| IPA | 格式（`/.../` 分隔符、长度、非中文字符） | 软警告 |
| 释义 | 中文长度、非单词本身 | 软警告 |
| 翻译 | 中文翻译以连词结尾（"然后""但是"等）→ 截断残留 | 软警告 |
| 例句 | 首字母小写 → 截断片段 | 软警告 |
| 例句 | 缺少定式动词 → 名词短语片段 | 软警告 |

# 共享工作流 — 句子匹配 / 翻译 / 内容生成 / 音频 / 同步

> 本文档供 `vocab-anki`（划线模式）和 `vocab-book`（全文模式）共用。
> `<skill_dir>` 为当前技能目录（`vocab-anki/` 或 `vocab-book/`）。
> `<tmp_id>` 为临时文件标识（划线模式用 `bookId`，全文模式用 `suffix`）。

## Step 3.0: 获取源文本（句子检索替代回忆）

**核心改进**：回忆式例句生成不可靠。改为从网上拉取书中实际文本，机械匹配每个生词所在句子，彻底消除编造风险。

### 3.0a. 搜索源文本

WebSearch `<英文书名> full text` 或 `<英文书名> <作者> full text`。优先选 Internet Archive（`archive.org`）、Project Gutenberg、Standard Ebooks。搜索时留意可直链下载的纯文本 URL（`.txt` 结尾或 `/download/` 路径）。

### 3.0b. 拉取源文本（curl 优先，WebFetch 兜底）

```bash
curl -sL --max-time 60 '<URL>' -o /tmp/<book>-full.txt
wc -c /tmp/<book>-full.txt
```

- curl 成功（文件 >20KB）→ 直接用
- curl 返回 HTML → 试 Internet Archive `/download/` 路径
- 全部失败 → WebFetch 逐章拉取
- 验证：`head -c 500` 确认是书中文本

**源文本语言要求**：必须使用英文原版。`match_sentences.py` 会拒绝含西里尔字母或 guillemet（«»）的文本——双语版源文本中的非英文元数据会污染句子匹配结果。搜索结果中优先选 Project Gutenberg（英文版）、Standard Ebooks、Internet Archive（英文原版）。

### 3.0c. 句子匹配

对每个待生成单词，在源文本中搜索（大小写不敏感）→ 提取所在完整句子。

- **章节优先匹配**（划线模式）：从 JSON 的 `in_coca[].chapters` 获取章节信息，优先在章节范围内搜索
- 匹配到 → 用 `<b>` 包裹目标词
- 未匹配到 → 标记 `⚠️`，回退回忆模式
- **全文模式无章节信息** → 全文本搜索

### 3.0c-1. 句子匹配校验

- 目标词表面词形实际出现在匹配到的句子中（大小写不敏感）
- 若找不到 → 扩大搜索，仍找不到 → `⚠️ 未匹配`
- 绝不在未确认时将 `word` 字段设为句中不存在的词形

### 3.0c-2. 句子完整性检查

- 必须有主语 + 定式动词谓语，不能是名词短语片段
- 首字符必须是大写字母或引号
- 禁止将片段写入 `sentence` 字段

### 3.0c-3. 扩展策略

若初始匹配是片段 → 向外扩展到完整句子边界。扩展后仍 >150 字符 → 交 3.0e 截断。

### 3.0d. 版本校验

搜一句书中知名台词确认版本。未匹配 → 版本可能不同，仍以源文本为准。

### 3.0e. 截断长句

若完整句子 >150 字符 → 截断，截断后必须是语法完整的句子。

截断优先级：
1. 保留主句主谓完整
2. 若生词在从句中 → 保留主句骨架 + 生词所在从句
3. 从后往前裁切（从句边界）
4. 以上都失败 → 在 max_len 内最后一个词边界处裁切

绝对禁止：
- 产出以非首字母大写开头的片段
- 产出纯名词短语（无谓语动词）
- 用 `…` 伪装片段
- 产出以连词开头的片段
- 截断切掉 `<b>` 标签
- 以功能词结尾

截断后自检：`<b>` 标签完整？句子以大写/引号开头？含义自包含？

> ⚠️ **硬性门控**：必须确认**所有**句子 ≤150 字符后，才能进入 Step 3.0f 翻译。
> 翻译基于截断后的最终句子。严禁先翻译后截断——会导致翻译与例句不一致。
> **验证方法**：检查译文末尾是否有截断残留（如中文以"然后""但是"等连词结尾）——
> 这是翻译前未截断的强信号。`sync_anki.py` 的校验步骤会对此发出警告。

源文本获取失败 → 该批次所有单词跳过。禁止回退词典例句。

## Step 3.0f: DeepL 翻译

**前置条件**：Step 3.0e 截断已完成，所有 sentence ≤150 字符。

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

若 DEEPL_API_KEY 未设置 → 跳过，翻译由 Claude 在 Step 3 完成。

## Step 3: 生成内容（Claude 知识工作）

仅对筛选出的单词生成内容。句子已从源文本提取，翻译已由 DeepL 完成（若可用）。

### 字段说明

| 字段 | 说明 |
|------|------|
| `word` | 书中表面词形 — `<b>` 包裹什么就写什么 |
| `lemma` | 派生形容词必填，常规屈折留空 |
| `coca_level` | 从 filter 输出 JSON **原样透传** |
| `sentence` | 含 `<b>…</b>` 的完整句子 |
| `ipa` | 对应 lemma 的 IPA（cmudict 自动生成；多发音词时 Claude 投票） |
| `definition_cn` | 按句中实际用法释义 |
| `translation_cn` | 整句中文翻译（优先 DeepL） |

### 例句规则

- 必须是书中真实句子，来自 3.0c 源文本机械匹配
- 禁止凭记忆编造；源文本没有 → 不生成卡片
- `<b>` 必须包裹句中完整的表面词形
- 例句 ≤150 字符

### 翻译规则

- **必须翻译机械匹配到的具体句子**，禁止从记忆中调取其他段落的译文
- 即使认出句子出自著名段落，也必须逐句翻译当前匹配结果，不得替换
- 翻译应与英文句子**语义严格对应**，不得出现英文说 A 中文翻 B 的情况
- 优先使用 DeepL（Step 3.0f）；Claude 翻译时更需警惕记忆干扰

### 分批策略

- ≤20 词 → 单批；21-40 → 2 批；41-60 → 3 批；60+ → 4+ 批
- 每批按字母序排列

### 每批自查清单

1. lemma 正确性（派生 adj 覆写，屈折留空）
2. IPA 对应性
3. 释义词性对齐
4. word 字段一致
5. 语义情境对齐（多义词义项验证）
6. sentence-translation 双向对齐

### 写入流程

优先 Python `json.dump`（避免 Write 工具 Unicode 归一化问题）：
```bash
python3 << 'PYEOF'
import json
data = { ... }
with open('/tmp/vocab-anki-input-<tmp_id>.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PYEOF
```

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

> IPA 由 cmudict 自动生成；Claude 仅多发音词时提供投票。此步骤不展示样卡，不询问用户。

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
| 句子 | 长度 ≤150 字符 | 硬错误 |
| 句子 | 必需字段非空（ipa, definition_cn, translation_cn） | 硬错误 |
| 句子 | lemma 合理性（不应比 surface form 长） | 硬错误 |
| 句子 | 句尾功能词（介词/连词结尾） | 硬错误 |
| 句子 | 标点残留（`,.` `,)` 等） | 硬错误 |
| IPA | 格式（`/.../` 分隔符、长度、非中文字符） | 软警告 |
| 释义 | 中文长度、非单词本身 | 软警告 |
| 翻译 | 中文翻译以连词结尾（"然后""但是"等）→ 截断残留 | 软警告 |
| 翻译 | EN→ZH 字符比异常（<0.3 或 >3.0）→ 可能错配 | 软警告 |
| 例句 | 首字母小写 → 截断片段 | 软警告 |
| 例句 | 缺少定式动词 → 名词短语片段 | 软警告 |

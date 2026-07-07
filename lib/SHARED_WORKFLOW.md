# 共享工作流 — 句子匹配 / 内容生成 / DeepL 翻译 / 音频 / 同步

> 本文档供 `vocab-anki`（划线模式）和 `vocab-book`（全文模式）共用。
> `<skill_dir>` 为当前技能目录（`vocab-anki/` 或 `vocab-book/`）。
> `<tmp_id>` 为临时文件标识（划线模式用 `bookId`，全文模式用 `suffix`）。

## Step 2A: 获取源文本 + 句子匹配 + POS 分析 + lemma + IPA

`match_sentences.py` 完成所有机械分析：源文本搜索、句子提取、spaCy POS 判定、lemma 产出、cmudict IPA。

### 2A-0. 检查缓存源文本（优先）

**每次执行 Step 2A 前，先查记忆中是否已记录该书的缓存路径。**

- 记忆命中（如 [[little-prince-source-text]]）→ 验证文件存在 → 使用缓存，跳过 2A-a/b
- 未命中 → 继续搜索

### 2A-a/b. 搜索并拉取源文本

WebSearch → curl 直链 → WebFetch 兜底。优先 Internet Archive / Project Gutenberg。验证英文原版。

### 2A-c. match_sentences.py — 全量候选 + POS 分组 + lemma + IPA

```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/match_sentences.py \
  /tmp/vocab-anki-input-<tmp_id>.json \
  <source_text_path>
```

脚本流水线：

1. 对每个 surface form，搜索源文本中**所有**出现位置（不限数量）
2. 每个出现 → 提取完整句子 → 跑 spaCy → 获取目标 token 的 `pos_/dep_/lemma_/tag_` + be-to 判定
3. 逐句判定 lemma：
   - `pos=ADJ` / `dep in (acomp,amod,attr,oprd)` → 形容词，不还原
   - `VBG + dep=amod` → 分词形容词，不还原
   - `spacy_lemma == word` → spaCy 拒绝还原，信任
   - `be_to == true` → 心理形容词（"was astonished to see"），不还原
   - `PROPN`（大写）→ 专有名词，不还原；小写 PROPN → 作 NOUN 处理
   - `ADV + word.endswith('ly')` → 副词，不还原
   - 其他 → lemminflect 正确 POS 通道
4. 按 `(lemma, pos)` 分组
5. 每组内 `select_best_sentence()` 选最佳句
6. cmudict IPA（从最终 lemma 查，fallback 到 surface form）
7. 按 `(lemma, pos)` 跨 entry 去重

输出 JSON：每个 `(lemma, pos)` 一个 entry，含 `lemma/word/pos/dep/spacy_lemma/be_to/coca_level/sentence/target_offset/ipa/candidates`。句子**不含 `<b>` 标签**。

### 2A-d. 版本校验 + 失败处理

源文本获取失败 → 该批次所有单词跳过。

---

## Step 2B: 句子审核 + 完整性校验 + 长句截断（Claude，1 agent）

> ⚠️ **不可绕过（MUST）**。Claude 的阅读能力是 Python 无法替代的——只有 Claude 能识别：
> - 序言/非正文句子（`char_offset` 靠前、内容为作者简介/编辑导语）
> - 语法不完整的句子片段
> - 语义不匹配的候选句

**目标词由 `target_offset` 定位**（不含 `<b>` 标签）。其余逻辑不变：完整性检查 → 长句截断 → 源文本手动提取。

截断规则不变：
- 目标 ≤250 字符，语法完整，含生词上下文
- 禁止切掉目标词、禁止以连词/功能词开头或结尾
- 截断后 regex 源文本校验

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

### 字段说明

| 字段 | 说明 |
|------|------|
| `word` | 书中出现的表面词形，JSON 中始终为表面词形 |
| `lemma` | match_sentences.py 机械产出，Claude 不可修改 |
| `coca_level` | 从 filter 输出透传 |
| `sentence` | 书中含该词的完整句子，不含 `<b>` 标签，`target_offset` 定位目标词 |
| `ipa` | match_sentences.py 从 cmudict 填充；未覆盖词由 Claude 补充 |
| `definition_cn` | 格式 `[词性] 释义`，按句中实际用法 |
| `translation_cn` | DeepL 提供的中文翻译 |

### 例句规则

- 必须是书中真实句子，来自 Step 2A 机械匹配
- 简洁：1-2 句，通常 ≤250 字符
- `<b>` 标签由 sync_anki.py 在同步时根据 `target_offset` 拼接

---

## Step 2F: 内容验证（Claude，1 agent）

> ⚠️ **不可绕过（MUST）**。

POS 对齐 + 释义准确 + 翻译一致性。`lemma` 不在此步检查（match_sentences.py 机械产出，不可修改）。

| 检查 | 说明 |
|------|------|
| POS 对齐 | `[词性]` 标注与句中实际用法一致 |
| 释义准确 | 代入验证法 + 义项枚举 + 跨句一致性 |
| 翻译一致性 | `definition_cn` 与 `translation_cn` 语义对齐 |

机械检查（word 匹配、IPA 格式、功能词结尾等）由 match_sentences.py 和 sync_anki.py 自动执行。

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

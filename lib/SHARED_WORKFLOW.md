# 共享工作流 — 句子匹配 / 内容生成 / DeepL 翻译 / 音频 / 同步

> 本文档供 `vocab-anki`（划线模式）和 `vocab-book`（全文模式）共用。
> `<skill_dir>` 为当前技能目录（`vocab-anki/` 或 `vocab-book/`）。
> `<tmp_id>` 为临时文件标识（划线模式用 `bookId`，全文模式用 `suffix`）。

## Step 2A: 获取源文本（句子检索替代回忆）

从网上拉取书中实际文本，机械匹配每个生词所在句子。

### 2A-0. 检查缓存源文本（优先）

**每次执行 Step 2A 前，先查记忆文件中是否已记录该书的缓存源文本路径。**

- 记忆文件命中（如 [[little-prince-source-text]] 记录了 `/tmp/tlp-full.txt`）→ 直接验证文件存在且 >50KB → **使用缓存**，跳过 2A-a 和 2A-b
- 记忆文件未命中 → 继续 2A-a 搜索

> 同一本书多次制作牌组时，记忆 + 缓存避免每次都用不同来源的源文本，确保跨批次句子一致性。下载后以 `/tmp/{safe_title}-{uuid8}-full.txt` 格式命名并写入记忆文件。

### 2A-a. 搜索源文本

WebSearch `<英文书名> full text` 或 `<英文书名> <作者> full text`。优先选 Internet Archive（`archive.org`）、Project Gutenberg、Standard Ebooks。搜索时留意可直链下载的纯文本 URL（`.txt` 结尾或 `/download/` 路径）。

**必须使用英文原版**——双语对照版中的非英文内容会污染句子匹配。`match_sentences.py` 遇到含西里尔字母或 guillemet（«»）的文本直接拒绝。

### 2A-b. 拉取源文本（curl 优先，WebFetch 兜底）

```bash
curl -sL --max-time 60 '<URL>' -o /tmp/<safe_book_title>-$(python3 -c "import uuid;print(uuid.uuid4().hex[:8])")-full.txt
wc -c /tmp/<safe_book_title>-*-full.txt
```

- curl 成功（文件 >20KB）→ 直接用，跳过 WebFetch
- curl 返回 HTML → 试 Internet Archive `/download/` 路径
- 全部失败 → WebFetch 逐章拉取
- 验证：`head -c 500` 确认是英文原版书中文本
- **下载验证通过后 → 将缓存路径写入记忆文件**（供下次 2A-0 查找），如 `[[{book-title}-source-text]]`

### 2A-b-1. 源文本版本选择

**选对源文本版本是最有效的质量控制**——坏的源文本（OCR 扫描版、带章节导航的网页提取版）导致的句子污染无法通过机械规则批量修复，只能逐句人工修正。

**优先顺序**：
1. Project Gutenberg / Standard Ebooks 的校对版纯文本（`.txt`）
2. Internet Archive 的扫描版（可能含 OCR 错误）
3. 网页逐章提取版（可能含章节导航标题粘连正文）

源文本有问题 → 换源重新拉取，不要勉强用损坏的文本生成例句。

### 2A-c. 句子匹配

对每个待生成单词，在源文本中搜索（大小写不敏感）→ 提取所在完整句子。

- **章节优先匹配**（划线模式）：从 JSON 的 `in_coca[].chapters` 获取章节信息，优先在章节范围内搜索
- 匹配到 → 用 `<b>` 包裹目标词
- 未匹配到 → 标记 `⚠️`，该词**不生成卡片**
- **全文模式无章节信息** → 全文本搜索
- PySBD 对话引号伪影（`" "No,`）由 `_clean_quote_artifact()` 自动清理

### 2A-c-1. 句子匹配校验（必做）

- 目标词的表面词形（如 `blundering`、`conceited`）实际出现在匹配到的句子中（大小写不敏感）
- 若句中找不到 → 扩大搜索，仍找不到 → `⚠️ 未匹配`
- **绝不**在未确认时将 `word` 字段设为句中不存在的词形

### 2A-c-2. 句子完整性检查（必做）

提取到的句子必须是**语法完整的句子**（有主语 + 定式动词谓语），不能是名词短语片段。

- **大写首字母检查**：去掉 `<b>` 标签后，首字符必须是大写字母或引号
- **主谓结构检查**：必须有可识别的主语 + 定式动词
- **禁止**在未确认完整性的情况下将片段写入 `sentence` 字段

### 2A-c-3. 扩展策略

若初始匹配是片段 → **向外扩展**到完整句子边界：
- **向前**：找到最近的句号/问号/感叹号 → 取其后的第一个大写字母作为句首
- **向后**：找到最近的句号/问号/感叹号 → 以该标点作为句尾
- 若扩展后仍 >250 字符 → 交由 Step 2B 截断处理

### 2A-d. 版本校验

源文本中搜一句书中知名台词确认版本。未匹配 → 版本可能不同，仍以源文本为准。

### 2A-e. 源文本获取失败

curl 直链 + WebSearch/WebFetch 均无法获取 → **该批次所有单词跳过**。Step 2H 汇总中标明 `源文本不可用，N 个单词未生成`。
**禁止回退到词典例句**。卡片的价值在于"这个词在这本书的这个句子里是这个意思"，没有源文本就没有卡片。

---

## Step 2B: 句子选择 + 完整性校验 + 长句截断（Claude，1 agent）

**在 2C/2D 生成释义之前执行**，避免为会被排除的词浪费时间。

从 match_sentences.py 输出的 candidates 中为每个词选句、做完整性校验、极端长句做语义截断。

### 输入

- `candidates` 数组（含 `<b>` 标签，按原文出现顺序，≤5 句）
- `char_offset`（词在源文本中的字符位置）
- `source_text_path`（源文本路径）
- 书上下文（书名 + 2-3 句情节简介，由主流程启动 agent 时写入 prompt）

### 执行流程

```
对每个 word:
  for sent in candidates:
    1. 句子选择：选最短的完整句（PySBD 已保证句子边界）

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

  全部 candidate 失败 →
    4. 回源文本手动提取（Read source_text_path offset=char_offset±500）
       → 目视完整句边界 → 手动切出 → 跑步骤 1-3
    5. 仍然失败 → excluded
```

### 截断规则

**截断目标**：≤250 字符、语法完整、含生词上下文的句子。

**截断优先级**（按序尝试，满足即停）：
1. **保留主句主谓完整**：主句的主语 + 谓语不可裁切。优先删除句尾的从属从句和修饰语
2. **若生词在从属从句中**：保留主句骨架 + 生词所在的完整从句
3. **从后往前裁切**：优先删除句尾的 `, and…`、`, which…`、`, so…` 等追加性分句
4. **不得已时保留完整长句**：若上述规则无法产出 ≤250 字符的完整句子 → 保留完整原文，sync_anki.py 会拒绝超长句子→返回重新处理

**绝对禁止**：
- 禁止产出以非首字母大写开头的片段（如 `the lights of…`）
- 禁止产出纯名词短语（无谓语动词）
- 禁止用 `…` 伪装片段为完整句子
- **禁止产出以连词开头的片段**：`and then, …`、`but they…`、`so that…` 等——若截断后自然句首是连词 → 继续回溯或放弃截断
- **禁止截断切掉 `<b>` 标签**：截断必须在 `<b>…</b>` 之后进行
- **禁止以功能词结尾**：介词（`from`、`with`、`at`、`for`…）、并列连词（`and`、`but`、`or`…）、助动词——截断点必须在实词或句末标点之后

**截断后自检**（每句截断后立即执行）：
1. `<b>…</b>` 标签完整存在且包裹正确的表面词形？
2. 句子是否以大写字母或 `"` / `'` 开头？
3. 句子含义是否自包含？
4. 若上述任一为否 → 放弃截断，使用更短的替代句子，或保留完整长句

**截断实施规范**（防止正则 bug）：

1. **截断前**：`print(repr(sent[-80:]))` 确认句尾精确文本，不要靠脑内模型写正则
2. **优先用显式字符串操作**：找到要删除的精确子串 → `sent.replace(exact_substring, replacement)`，避免用 `$` 锚点的模糊正则
3. **截断后立即验证**：打印结果句尾，检查列表项不重复、语法完整
4. **修复时回源**：若截断结果异常 → 回到 `match_sentences.py` 输出的原始 candidate，不要用已被污染的 JSON

**翻译对应规则**：`translation_cn` 必须只翻译截断后的最终 `sentence`，不得翻译截断前的完整原文。

### 共享句 `<b>` 标签校验

多个词共享同一句时（如 `cram` 和 `obstruct`），每个词的 `sentence` 中 `<b>` 标签必须包裹**该词自己的表面词形**，不能把共享词的标签原封不动复制过来。

```
❌ pardon: "...you will <b>pardon</b> him...for he must be treated thriftily."
   thriftily: "...you will <b>pardon</b> him...for he must be treated thriftily."  ← 标签在 pardon 上
✅ pardon: "...you will <b>pardon</b> him...for he must be treated thriftily."
   thriftily: "...you will pardon him...for he must be treated <b>thriftily</b>."
```

---

## Step 2C: IPA 预填充（cmudict 批量生成）

> `sync_anki.py` 验证要求 `ipa` 字段非空。在 Claude 生成释义之前用 cmudict 批量填充 IPA，2D 只处理 cmudict 未覆盖的词和异读词投票。

```bash
cd <skill_dir> && .venv/bin/python3 << 'PYEOF'
import json, sys
sys.path.insert(0, '.')
from lib.sync_anki import _cmu_ipa, resolve_lemma

with open('/tmp/vocab-anki-input-<tmp_id>.json') as f:
    data = json.load(f)

missing_cmudict = []
for w in data['words']:
    if w.get('ipa') and '/' in w['ipa']:
        continue
    lemma = resolve_lemma(w['word'], w.get('lemma', '').strip())
    cmu = _cmu_ipa(lemma)
    if cmu:
        w['ipa'] = cmu
    else:
        missing_cmudict.append(f"{w['word']}/{lemma}")

if missing_cmudict:
    print(f"Words not in cmudict ({len(missing_cmudict)}):")
    for m in missing_cmudict:
        print(f"  {m}")
    print("2D must provide IPA manually for these words.")

with open('/tmp/vocab-anki-input-<tmp_id>.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"IPA filled from cmudict, JSON written")
PYEOF
```

cmudict 未覆盖的词由 Claude 在 2D 中手动补充。

---

## Step 2D: 生成内容（Claude，N agents 并行）

用 2B 确定的最终句子，为每个词生成 `definition_cn` + 手动补充 cmudict 未覆盖词的 IPA + 异读词投票。

**分批**：≤25 词/agent。≤30→1, 31–80→4, 81–200→8, 200+→10+。每批按字母序排列。
**不自查**——自查职责移至 2E。

### 2D-0. lemma 判定（生成内容前必做）

对每个 `-ed`/`-ing` 结尾的词，**先跑 spaCy 把标注写进 JSON，Claude 拿着标注读句子判断**：

```bash
cd <skill_dir> && .venv/bin/python3 << 'PYEOF'
import json, sys
sys.path.insert(0, '.')
from lib.sync_anki import _get_spacy
nlp = _get_spacy()

with open('/tmp/vocab-anki-input-<tmp_id>.json') as f:
    data = json.load(f)

for w in data['words']:
    wl = w['word'].lower()
    if not wl.endswith(('ed', 'ing')):
        continue
    sent = w.get('sentence', '')
    if not sent:
        continue
    doc = nlp(sent)
    for token in doc:
        if token.text.lower() == wl:
            lemma_self = token.lemma_.lower() == wl
            be_to = False
            if token.tag_ == 'VBN':
                be_forms = {'am','is','are','was','were','be','been','being'}
                has_be = any(
                    doc[i].text.lower() in be_forms
                    for i in range(max(0, token.i - 3), token.i)
                )
                if has_be:
                    for j in range(token.i + 1, min(token.i + 3, len(doc))):
                        if doc[j].text.lower() == 'to' and j + 1 < len(doc):
                            be_to = doc[j + 1].pos_ == 'VERB'
                            break
            w['_spacy'] = {
                'pos': token.pos_, 'tag': token.tag_, 'dep': token.dep_,
                'spacy_lemma': token.lemma_,
                'self_lemma': lemma_self, 'be_to': be_to,
            }
            break

with open('/tmp/vocab-anki-input-<tmp_id>.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("spaCy annotations written to JSON")
PYEOF
```

脚本在每个 `-ed`/`-ing` 词上写入 `_spacy` 字段，JSON 变为：

```json
{"word": "disheartened", ..., "_spacy": {"pos": "VERB", "tag": "VBN", "dep": "ROOT", "spacy_lemma": "dishearten", "self_lemma": false, "be_to": false}}
```

**Claude 逐词判断**（Step 2D 生成每个词时，读它的 `_spacy` + `sentence`）：

```
对每个 -ed/-ing 词：
  看 _spacy 标注：
    pos=ADJ 或 dep=acomp/amod → 确定是形容词 → lemma = word
    self_lemma=true           → spaCy 拒绝还原    → lemma = word
    be_to=true                → 情感形容词模式    → lemma = word
    以上都不满足               → 跑 two-step 测试后判断：

  Step A — "very + word" 形容词测试（必做）：
    把 "very" 放在词前读一遍 → 自然吗？
      自然   → 形容词 → lemma = word（例：very disheartened ✓）
      不自然 → 动词   → 继续 Step B

  Step B — "by" 短语陷阱：
    句中有 "be + -ed + by" 结构？
      by 后是情绪/状态的原因（failure, news, journey）→ 形容词 → lemma = word
      by 后是动作的执行者（guard, police, mechanic）  → 被动语态 → 看主句语义
      不确定 → lemma = word（保守）

  最终判断：
    描述状态/性质 → lemma = word
    描述具体动作   → lemma 留空
    不确定         → lemma = word（保守）
```

> **⚠️ 关键陷阱**：`be + -ed + by` 不一定是被动语态。情绪类 -ed 词 + `by`（disheartened by, excited by, disappointed by, tired by）几乎总是形容词描述状态，`by` 表原因而非施动者。spaCy 会将此类词标为 `VERB/VBN`，**不可盲从**。
>
> `_spacy` 是参考数据，**不是最终判定**。Claude 必须读句子确认——spaCy 可能把形容词标为 VERB（如 disheartened）。最终 `lemma` 写入 JSON 的 `lemma` 字段，`resolve_lemma` 无条件信任。

### 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 书中出现的**表面词形**——`<b>` 包裹什么就写什么。JSON 中始终为表面词形，用于 `sync_anki.py` 校验 `<b>` 文本一致性。卡片正面 `Word` 字段由 `resolve_lemma()` 另行决定：规则屈折还原为原形，派生形容词保留表面词形 | `pondered`（JSON `word`=`pondered`，卡片正面显示 `ponder`）；`blundering`（JSON `word`=`blundering`，`lemma`=`blundering`，卡片正面显示 `blundering`）|
| `lemma` | **派生形容词时必填，常规屈折变化可留空**。三层防护：(1) Claude 显式设置的 `lemma` **无条件信任**；(2) 若留空，`resolve_lemma()` 用 lemminflect + COCA 守卫自动还原；(3) spaCy 读原句校验——对 `-ed`/`-ing` 词判定为形容词则阻止还原 | `pondered`→留空；`accomplished`(adj)→`"accomplished"`|
| `coca_level` | **从 filter 输出透传** | `5` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹（2B 已确定） | `I felt awkward and <b>blundering</b>.` |
| `ipa` | 大部分已由 2C cmudict 填充；2D 补充未覆盖词 + 异读词投票 | 单发音词留空；异读词填 `/riːd/`（非 `/red/`）|
| `definition_cn` | **格式**：`[词性] 释义`。词性用 `[n.]` `[v.]` `[adj.]` `[adv.]` `[prep.]` `[conj.]`。释义**按句中实际用法**。**禁止**在释义后加括号补充说明 | `inquiry` 在 "came a timid inquiry"→`[n.] 询问，提问` |
| `translation_cn` | 整句中文翻译，由 Step 2F DeepL 提供。`DEEPL_API_KEY` 未设置时留空 | `我于是对丛林中的冒险深深思索起来。` |

### 例句规则

- 必须是书中真实句子，不是词典通用例句。句子来源只有一条路径：2A-c 源文本机械匹配。源文本中没有该词的句子 → 该词不生成卡片
- **禁止凭记忆编造特定书的句子**——2A-c 机械匹配会校验词形是否存在于句中，编造的句子无法通过此检查
- **禁止使用词典例句替代**——词典例句脱离书中语境，对阅读理解没有帮助
- 句子中出现的生词形式可能不同于原形，用 `<b>` 包裹书中实际出现的词形。**`<b>` 必须包裹句中完整的表面词形**——例如句中写的是 `considerably`，就写 `<b>considerably</b>`，**禁止**写 `<b>considerable</b>ly`
- **`<b>` 目标词校验**：句子中 `<b>` 包裹的词必须与 JSON `word` 字段（表面词形）一致——`sync_anki.py` 第 870 行自动执行此校验。卡片正面 `Word` 字段可能是原形（规则屈折还原后），这不影响 `<b>` 校验。例如 `pondered`：`<b>pondered</b>` = JSON `word`=`pondered` → 一致 ✅，卡片正面显示 `ponder` 由 `resolve_lemma()` 控制
- 例句应简洁：1-2 句，通常 ≤250 字符

### 派生形容词 COCA 复查

`lemmatize_word` 将派生 adj 还原为词根（`blundering`→`blunder`）。两层防护：
1. **Claude 逐批校验**：确认句中用法为派生形容词 → 显式设置 `lemma`
2. **spaCy 同步前校验**：对 `-ed`/`-ing` 词，spaCy 读原句判断词性——若为形容词，阻止 `resolve_lemma()` 还原

若派生形容词的自身不在 BNC/COCA 25000 词族中 → **不生成卡片**，加入 `excluded` 数组。

### 执行策略

> **禁止预先思考全部单词**——按批次边写边想，每批写完再想下一批。读完 pipeline 输出后，**先执行 Step 2A 拉取源文本**，从源文本中机械匹配所有单词的句子。然后在写入 JSON 时直接填入已提取的句子。

### JSON 写入

**优先用 Python `json.dump`**——Write 工具可能将中文弯引号（`""`）归一化为 ASCII `"`，破坏 JSON 定界符。

```bash
python3 << 'PYEOF'
import json
data = {
    "book_title": "...",
    "book_author": "...",
    "deck_name": "...",
    "book_id": "<bookId>",     # 划线模式（与 suffix 二选一）
    # "suffix": "<uuid>",      # 全文模式（与 book_id 二选一）
    "words": [...],
    "excluded": [...],
}
with open('/tmp/vocab-anki-input-<tmp_id>.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PYEOF
```

> **`book_id` 与 `suffix` 二选一**：划线模式传入微信读书 `bookId`，全文模式传入 `filter_fulltext.py` 生成的 `suffix`。sync_anki.py 自动识别两个字段，用于 WordId 构建和音频文件命名。

> Write 工具备用方案：第一批前 `rm -f + touch + Read limit=3` 初始化；后续批次 `Read limit=5` 定位 + `Edit` 追加。

---

## Step 2E: 内容验证（Claude，1 agent）

POS 对齐 + 释义准确。仅校验 Claude 产出，不涉及翻译。发现问题 → 直接修正。

| 检查 | 说明 |
|------|------|
| POS 对齐 | `[词性]` 标注与句中实际用法一致？比较级 passive-vs-adjective 判定标准 |
| 释义准确 | 代入验证法 + 义项枚举 + 跨句一致性检查 |

机械检查（word=`<b>` 标签、IPA 格式、功能词结尾等）由 match_sentences.py 和 sync_anki.py 纵深防御执行，不在 2E。

---

## Step 2F: DeepL 翻译

例句翻译全部交给 DeepL API 完成，**Claude 不参与翻译也不校验翻译结果**。

在 **2E 之后、2G 之前**执行，翻译已确定的最终句子。中途中断不浪费翻译配额。

前置条件：`DEEPL_API_KEY` 环境变量。**未设置则跳过翻译**，`translation_cn` 字段留空。

```bash
if [ -n "$DEEPL_API_KEY" ]; then
    <skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/translate_deepl.py \
      /tmp/vocab-anki-input-<tmp_id>.json \
      --source-text <source_text_path>
else
    echo "DEEPL_API_KEY 未设置，跳过翻译"
fi
```

脚本行为：
- 剥离 `<b>` 标签 → DeepL（`target_lang=ZH`）
- **自动去重**：相同句子只翻译一次，译文回填所有共享该句的词
- **上下文（`--source-text`）**：找到目标句原文位置，取前 2 句作为 DeepL `context` 参数
- 翻译写回 `translation_cn`，打印去重数量、字符用量

---

## Step 2G: 预下载音频（并发，不依赖 Anki）

```bash
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

cd <skill_dir> && .venv/bin/python -u -m lib.sync_anki \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --prefetch -v
```

输出末尾 `AUDIO_DIR=<path>`，供 Step 2H 使用。失败项会阻塞同步——`edge_tts_bytes` 已内置 3 次重试，全部失败后抛 RuntimeError。

---

## Step 2H: 最终确认 + 同步（唯一确认点）

### 展示汇总

- 音频状态、本次新增单词（lemma）、源文本校验状态、lemma 覆写数量
- Anki 已有的词仅一句话带过数量，不列出

### 空跑判定

本次新增为空且新增排除为空 →「没有新的生词」，终止，**不询问用户**。

### 确认

仅问一次：「确认同步？」

### 执行（音频已预下载，秒级完成）

```bash
WORD_COUNT=$(python3 -c "import json; print(len(json.load(open('/tmp/vocab-anki-input-<tmp_id>.json'))['words']))")
SYNC_TIMEOUT=$(( WORD_COUNT * 3 + 30 ))
[ "$SYNC_TIMEOUT" -lt 60 ] && SYNC_TIMEOUT=60

timeout $SYNC_TIMEOUT bash -c "cd <skill_dir> && .venv/bin/python -u -m lib.sync_anki \
  /tmp/vocab-anki-input-<tmp_id>.json \
  --audio-dir <AUDIO_DIR_FROM_STEP_2G> \
  -v"
```

**同步超时处理**：
- 正常完成 → 展示同步结果
- 超时退出（exit 124）→ 告知用户重试
- 非零退出码 → 打印 stderr

### 同步详情

1. `--prefetch`：并发生成音频 → manifest.json → `AUDIO_DIR=<path>`
2. `--audio-dir <dir>`：加载音频 → AnkiConnect → 查已有 → 上传 → 添加
3. 音频命名：`{lemma}_{<tmp_id>}_word.mp3` / `{lemma}_{<tmp_id>}_sent.mp3`
4. 已有卡片完全不动，保留复习进度和调度数据
5. 全文模式自动频次分级（`compute_bands()`）：COCA 级别 → 贪心分割 → 层级牌组
6. 触发 AnkiWeb 同步（fire-and-forget）

牌组名决议优先级（`sync_anki.py` 自动执行）：

1. **Anki 已有牌组**（最高优先）：`find_deck_for_book_id()` 按 bookId 搜索已有卡片，以 Anki 实际牌组名为准——防止不同批次间重音符号/拼写漂移（如 `Saint-Exupery` vs `Saint-Exupéry`）
2. JSON `deck_name` 字段（Claude 在 Step 0b 从 `cardsInfo` API 获取）
3. `--deck` CLI 参数
4. 自动推导：`{book_title} ({book_author})`

---

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

---

## 同步后审计（Step 2H 完成）

逐张检查 Anki 卡片，重点查三类问题：

1. **Word ≠ `<b>` 文本且不是合法原形还原**：`heal` + `<b>healer</b>` ❌（`healer` 是独立名词不是屈折形式）
2. **Word 被截断**：`lavend`/`silv`/`weath`/`nause` 等——原形不完整
3. **Word 大小写异常**：`Amen`/`Champion` 等专有名词或句首大写泄漏——应统一为小写

审计命令：
```bash
<skill_dir>/.venv/bin/python3 <skill_dir>/lib/scripts/audit_deck.py "牌组名"
```

### 自动校验（sync_anki.py 内置）

| 类型 | 检查项 | 级别 |
|------|--------|------|
| 源文本 | 含西里尔/guillemet → 拒绝 | 硬错误 |
| 句子 | `<b>` 标签与 word 字段一致 | 硬错误 |
| 句子 | 目标词实际出现在句中 | 硬错误 |
| 句子 | 长度 ≤250 字符 | 硬错误 |
| 句子 | 必需字段非空（ipa, definition_cn, translation_cn） | 硬错误 |
| 句子 | lemma 合理性（不应比 surface form 长） | 硬错误 |
| 句子 | 句尾功能词（介词/连词结尾） | 硬错误 |
| 句子 | 标点残留（`,.` `,)` 等） | 硬错误 |
| IPA | 格式（`/.../` 分隔符、长度、非中文字符） | 软警告 |
| 释义 | 中文长度、非单词本身 | 软警告 |
| 翻译 | 中文翻译以连词结尾（"然后""但是"等）→ 截断残留 | 软警告 |
| 例句 | 首字母小写 → 截断片段 | 软警告 |
| 例句 | 缺少定式动词 → 名词短语片段 | 软警告 |

---

## 翻译原则

> 准确、自然、可追溯。每个关键词汇在中文里要有对应，让学习者能从句子的中文字面反推出英文结构。

- **句式按中文习惯调整**：英文的代词、从句、被动语态大胆打破，换成中文流水句
- **动词优先选用与英文义项直接对应的词**：`intimated` → "暗示"（而非"婉转地表示"）
- **不要重新创作**：翻译的目的是辅助理解英文原句，不是独立的中文美文
- **多义词语境陷阱**：不要自动选择最常见义项。回到原文判断该词在此句中具体表达什么意思

---

## IPA 规则

- **IPA 必须对应 lemma（卡片展示词）**——卡片正面显示的是原形，音标应与卡片展示词一致
- **IPA 由 cmudict（CMU Pronouncing Dictionary，134K 词）自动生成**——Claude 仅在多发音词时投票，未登录词时兜底
- **多发音词（heteronym）**：cmudict 提供候选发音，Claude 的 `ipa` 字段用作投票选出正确发音。若 Claude 未填 IPA，取 cmudict 第一候选
- **未登录词**：cmudict 查不到的词退回 Claude 的 `ipa` 字段
- 单词音频由 Edge TTS 默认发音生成
- IPA 缺失时跳过单词音频生成，卡片仍正常创建（例句音频正常生成）

---

## 卡片字段更新依赖规则（硬性要求）

修改一个字段时，依赖字段必须同步更新：

| 修改的字段 | 必须同步更新的依赖字段 | 不需要更新的 |
|-----------|---------------------|------------|
| `lemma` | `ipa`、单词音频、`definition_cn` | `sentence`、`word` |
| `word` | 同 `lemma` | `sentence` |
| `sentence` | 例句音频、`translation_cn`、`word`、`definition_cn` | — |

`definition_cn` / `translation_cn` 更新判断：

| 变更 | 是否需要更新 | 判断依据 |
|------|------------|---------|
| 修复截断（句子变短，同语境） | 否 | 词义在句中未变 |
| 换到不同句子 | **检查** | 同一词在新句中可能是不同义项 |
| 修正 `word`/`lemma` | **必须** | 词变了，释义对应不同词 |
| 拼写/大小写修正 | 否 | 词没变 |

**执行流程**：
1. 修改源 JSON 中的字段
2. 重新运行 `sync_anki.py --prefetch` 生成新音频
3. 重新运行 `sync_anki.py --audio-dir <dir>` 上传新媒体并更新 Anki 卡片
4. 若是修复已在 Anki 中的单张卡片：用 AnkiConnect API 直接更新 `fields` 并上传新媒体

> 修改任一字段后必须执行上述完整流程——只更新 JSON 不重跑音频会导致卡片字段不一致（旧音频配新句子、旧释义配新词形）。

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
    {"word": "pondered", "lemma": "ponder", "coca_level": 3, "ipa": "/.../", "sentence": "...", "definition_cn": "...", "translation_cn": "..."}
  ],
  "excluded": [
    {"word": "abash", "reason": "不在 BNC/COCA 25000 词族中"}
  ]
}
```

- `book_id` 和 `suffix` 二选一，不可同时为空。划线模式使用 WeRead bookId，全文模式使用 filter_fulltext.py 生成的 UUID suffix。sync_anki.py 自动识别两个字段。

- `ipa` 由 cmudict 自动生成；Claude 仅在多发音词时提供投票参考
- `coca_level` 从 filter 输出原样透传
- `excluded[].word` 使用 `lemma` 字段（非 `rep`），确保排除词以原形展示
- **此步骤不展示样卡，不询问用户**

---

## 异常处理（共享）

| 情况 | 处理 |
|------|------|
| 源文本不可用 | curl + WebSearch/WebFetch 均无法获取 → 该批次所有单词跳过 |
| 音频生成失败 | Edge TTS 重试 3 次后仍失败 → 抛 RuntimeError 阻塞同步 |
| 脚本运行失败 | 检查依赖安装、网络连接，打印错误信息 |
| AnkiConnect 不可达 | 提示启动 Anki 并安装插件；远程环境使用 `ssh -R 8765:localhost:8765` 反向隧道 |
| 同步脚本超时 | 提示原因，建议重试 |
| 没有新生词 | 直接告知用户，流程自动结束 |

---

## 设计原则（共享）

- **职责分离**：Claude 做知识工作（释义、IPA 异读词投票），DeepL 做机械翻译，Python 做机械工作（TTS、同步）。句子提取由 Step 2A 源文本检索完成
- **例句来自源文本机械匹配**：不依赖 Claude 记忆，从书中实际文本提取
- **curl 优先于 WebFetch**：源文本拉取优先用 `curl -sL` 直链下载；WebFetch 仅作 curl 失败时的逐章兜底
- **章节优先匹配**（划线模式）：优先在单词所属章节范围内搜索句子，避免同名异义词串章
- **表面词形严格匹配**：必须验证匹配到的词与目标词形一致（大小写不敏感），不一致时排除
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响
- **过滤前置**：Anki 去重和 COCA 频次检查在生成内容之前完成；已在牌组中的词不受 COCA 频次变化影响
- **确认前置音频**：确认前预下载，确认后秒级同步，用户不被阻塞
- **一次性确认**：整个流程仅在最终同步前确认一次

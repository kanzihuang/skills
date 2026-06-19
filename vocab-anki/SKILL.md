---
name: vocab-anki
description: >
  Generate Anki vocabulary flashcard decks (.apkg) from WeRead (微信读书)
  English book highlights. Supports two modes: (1) export .apkg file for manual
  import, (2) sync directly to Anki via AnkiConnect plugin. Use when user wants
  to create Anki cards from WeRead highlights, e.g. "/vocab-anki The Little Prince"
  or "为这本书的划线生词生成 Anki 牌组". Integrates with weread-skills for data;
  Claude does knowledge work (sentences, translations), Python scripts handle
  audio + packaging + sync.
---

# vocab-anki — 英文书词汇 Anki 牌组生成

将微信读书英文原版书的划线生词转换为 Anki 牌组（`.apkg`），嵌入发音音频。
支持两种交付模式：
- **导出一**：生成 `.apkg` 文件，手动导入 Anki
- **同步二**：通过 AnkiConnect 直接同步到正在运行的 Anki，自动对比已有卡片，仅添加新词

## 前置条件

- `weread-skills` 已安装，`WEREAD_API_KEY` 环境变量已设置
- Python 3 + venv（脚本会自动创建 venv 并安装依赖）
- **同步模式额外需要**：Anki 正在运行 + [AnkiConnect 插件](https://ankiweb.net/shared/info/2055492159) 已安装

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
- 若有卡片 → 对每个使用 "Vocabulary Card (WeRead)" 模型的牌组，取一张卡片的 `WordId` 字段（格式 `{lemma}_{bookId}`），解析出 `bookId`。形成映射表：

```
{牌组名: bookId}
```

**目的**：用 bookId 作为 Anki ↔ 微信读书的精确桥接。bookId 来自卡片字段，无需额外存储——每张卡片的 WordId 天然包含 bookId。

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

**1d. 筛选 + 原形去重（单次 Python 流水线，不含 COCA，不询问用户）：**

> 此步骤仅做机械提取和去重。COCA 检查延后到 Step 1f（Anki 去重之后）。

```bash
# 确保 venv 存在（仅首次）
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 提取划线 → 过滤 → 原形去重（不含 COCA）
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/book/bookmarklist","bookId":"<bookId>","skill_version":"1.0.3"}' | \
<skill_dir>/.venv/bin/python3 -c "
import sys, json
sys.path.insert(0, '<skill_dir>')
from utils import lemmatize_word

data = json.load(sys.stdin)
# 校验 API 响应结构：缺少 updated 字段 = API 调用失败（认证错误/bad bookId/网络问题）
if 'updated' not in data:
    err_info = data.get('errmsg', '') or data.get('error', '') or f'keys: {list(data.keys())}'
    print(f'ERROR: API response missing "updated" field — possible auth failure or bad bookId. Response hint: {err_info}', file=sys.stderr)
    sys.exit(1)
# 提取所有划线文本
marks = [h.get('markText','').strip() for h in data.get('updated',[])]
# 过滤非单词（含空格、纯数字/符号、空、长度=1）
words_raw = [m for m in marks if m and ' ' not in m and not m.isdigit() and len(m) > 1]
# 原形去重
lemma_map = {}
for w in words_raw:
    lemma = lemmatize_word(w)
    if lemma not in lemma_map:
        lemma_map[lemma] = []
    lemma_map[lemma].append(w)
# 输出
print(f'SUMMARY: {len(marks)} highlights → {len(lemma_map)} lemmas')
print('---ALL_LEMMAS---')
for lemma in sorted(lemma_map.keys()):
    forms = lemma_map[lemma]
    rep = min(forms, key=lambda x: (x[0].isupper(), len(x)))
    print(f'{lemma}\t{rep}\t{\",\".join(forms)}')
"
```

输出：`SUMMARY:` 行 + `---ALL_LEMMAS---` 表（lemma \t rep \t forms）。Claude 解析后用于下一步。

**1e. Anki 去重（先于 COCA，基于原形，不询问用户）：**

> 输入为 Step 1d 输出的**全部**原形列表。Anki 去重先于 COCA 执行——已在牌组中的词直接跳过，不再受 COCA 影响。

- **若 Step 0b 已确认全库 0 张 Vocabulary Card (WeRead) 笔记 → 直接 A=0，跳过本步骤。**
- 否则：
  1. **先读 meta manifest**：查 `WordId = __META__{bookId}` → 解析 `excluded` 获取历史排除词
  2. 查目标牌组已有卡片 WordId（格式 `{lemma}_{bookId}`），匹配则跳过
- 输出 Anki 去重后的剩余原形列表，供 Step 1f 做 COCA 检查

**1f. COCA 批量检查（Anki 去重之后，不询问用户）：**

> 仅对 Step 1e Anki 去重后**剩余**的原形做 COCA 检查。已在牌组中的词不参与 COCA。
> 
> `in_coca()` 的 lemminflect/后缀剥离兜底**不是冗余**——Step 1d 的 `lemmatize_word()` 仅做屈折归一（pondered→ponder），故意不碰派生词（indulgently 保持原样）。但 COCA 20000 不直接收录所有派生形式（有 `indulgent` 无 `indulgently`），需要兜底做派生归一。见设计原则"原形归一（两层分工）"。

```bash
# COCA 检查：从 stdin 读取原形列表（每行 lemma\trep\tforms），输出 IN_COCA / EXCLUDED
echo '<TAB_SEPARATED_LEMMA_LIST>' | \
<skill_dir>/.venv/bin/python3 -c "
import sys, json
sys.path.insert(0, '<skill_dir>')
from coca_lookup import load_coca, in_coca

coca_set = load_coca()
passed = []
rejected = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    parts = line.split('\t')
    lemma = parts[0]
    rep = parts[1]
    forms_str = parts[2] if len(parts) > 2 else rep
    ok, _ = in_coca(lemma, coca_set)
    if ok:
        passed.append((lemma, rep, forms_str.split(',')))
    else:
        rejected.append((lemma, rep, '不在 COCA 20000 中'))

print(f'SUMMARY: {len(passed)} in COCA → {len(rejected)} excluded')
print('---IN_COCA---')
for lemma, rep, forms in passed:
    print(f'{lemma}\t{rep}\t{\",\".join(forms)}')
print('---EXCLUDED---')
for lemma, rep, reason in rejected:
    print(f'{lemma}\t{rep}\t{reason}')
"
```

输出分为三段：`SUMMARY:` 行、`---IN_COCA---` 表、`---EXCLUDED---` 表。

**Step 1 汇总（仅数字，不确认）：**

> Step 1d → 1e → 1f 连续执行，中间不暂停、不询问用户。

```
划线 X 条 → 原形去重 Y 个 → Anki 已有 A 个 → COCA 排除 B 个 → 待生成内容 C 个
```

> Anki 去重先于 COCA：已在牌组中的词直接保留，不受 COCA 频次影响。COCA 仅对真正的新词做筛。所有检查均为本地/本地网络查询（毫秒级），无需缓存。

### Step 3: 生成内容（Claude 知识工作，范围收窄）

仅对 Step 1 筛出的 C 个单词生成内容。对每个单词提供：

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 生词（书中出现的表面词形，脚本建卡用原形，已在 Step 1d 做过原形归一） | `pondered` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹 | `I <b>pondered</b> deeply, then, over the adventures of the jungle.` |
| `ipa` | IPA 音标（如已知；否则留空由脚本自动获取） | `/ˈpɒndər/` |
| `definition_cn` | 在该书上下文中的中文释义 | `沉思，深思` |
| `translation_cn` | 整句的中文翻译（遵循翻译原则） | `我于是对丛林中的冒险深深思索起来。` |

**例句规则（不变）：**
- 必须是书中真实句子，不是词典通用例句
- 如果对该书不够熟悉，无法回忆真实句子 → 如实告知用户，并提供词典例句作为替代
- 句子中出现的生词形式可能不同于原形（如 `straying` vs `stray`），用 `<b>` 包裹书中实际出现的词形
- 句子应完整、有语境，不是片段

**翻译原则：**

> 准确、自然、可追溯。每个关键词汇在中文里要有对应，让学习者能从句子的中文字面反推出英文结构。不要逐字死译，也不要重新创作。

- **关键词映射可追溯**：`absence of reproaches` → "没有一句责备的话"（`absence`→"没有"、`reproaches`→"责备的话"），而不是"毫无责备之意"（丢失了 `absence` 的映射）
- **句式按中文习惯调整**：英文的代词、从句、被动语态大胆打破，换成中文流水句。但词义不走样
- **动词优先选用与英文义项直接对应的词**：`intimated` → "暗示"（而非"婉转地表示"），`linger` → "徘徊"（而非"流连"），确保学习者能根据中文反查英文原词
- **不要重新创作**：翻译的目的是辅助理解英文原句，不是独立的中文美文

**IPA 规则：**
- **必须为每个单词提供 IPA**——Claude 可从训练数据直接输出音标，无需外部 API
- 提供 IPA 后脚本用 SSML `<phoneme>` 合成单词音频，完全跳过 Free Dictionary API（省去每词 ~0.5-2s 的网络请求 + `API_DELAY`）
- Free Dictionary API 仅作为脚本端兜底（IPA 缺失时），正常情况下不触发
- 对同形异音词（heteronym，如 `intimate` 形容词 /ˈɪntɪmət/ vs 动词 /ˈɪntɪmeɪt/），必须根据释义填入正确 IPA

**释义审查：**
- 在 COCA 表中的单词，判断释义是否为罕见用法（古英语义、专业术语、已淘汰的表达）。若罕见 → 不收录
- 若书中没有合适的例句 → 不收录

**执行策略：**

- 所有单词由 Claude 在单次响应中直接生成全部内容（IPA、例句、释义、翻译），按字母序写入 JSON 文件
- **不再使用 SubAgent**：SubAgent 启动慢（权限确认、模型初始化），常误触发 WebSearch 浪费额度，多个 agent 的协调开销远超串行生成的实际耗时
- **知名书禁止 WebFetch/WebSearch**：对于 Claude 训练数据中充分覆盖的知名英文书（The Little Prince、Harry Potter、Animal Farm、1984、Pride and Prejudice、Charlotte's Web 等），**严禁使用 WebFetch 或 WebSearch**——直接从训练数据回忆书中真实例句。查外部资源只会浪费时间，且 WebFetch 可能被网络策略拦截导致流程卡死
- 对于不熟悉的书籍：如 Claude 确实无法从训练数据回忆该书的句子，**仅此时**才用 `WebFetch` 一次性获取书中段落辅助定位

**性能说明：**
- 内容生成本身是流程瓶颈（Claude 需要为每个词回忆句子+IPA+释义+翻译），对 50+ 单词通常需要 1-3 分钟，这是知识工作的固有开销，不可免
- JSON 写入**必须使用 `Write` 工具**而非 Bash heredoc——Write 直接写文件系统，跳过 shell 缓冲和序列化开销，省 ~10-15s
- 文件尚不存在时先 `Bash touch /tmp/vocab-anki-input-<bookId>.json` 创建空文件，再用 `Write` 工具写入

**完成后：**构建 JSON 写入 `/tmp/vocab-anki-input-<bookId>.json`：
- `book_title` 和 `book_author` 来自 Step 1 的解析结果（已有牌组则来自牌组名，否则来自微信读书 API）
- `book_id` 为微信读书 bookId
- `ipa` 为必填（Claude 直接提供）；脚本用 SSML `<phoneme>` 合成音频，跳过 Free Dictionary API
- `excluded` 数组记录未收录的单词及原因
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

### Step 4: 最终确认 + 同步/导出（唯一确认点）

**4a. 展示最终汇总（含音频预下载状态）：**

- **新增排除**：本轮 COCA 检查中新发现不在表中的词（单词 + 原因）
- **音频状态**：Step 3.5 结果（如 `word✓ 64/64, sent✓ 62/64`）
- **本次新增**：将同步的单词列表（仅单词名，不展示样卡）
- Anki 已有的词仅一句话带过数量，不列出

**4b. 空跑判定：**

若本次新增为空 **且** 新增排除为空 → 直接回复「没有新的划线生词」，终止流程，**不询问用户**。

**4c. 唯一确认：**

展示汇总后，仅问一次：「确认同步？」（或导出模式下「确认导出？」）。

**4d. 执行（音频已预下载，秒级完成）：**

> 音频已在 Step 3.5 预下载到临时目录。同步阶段仅上传媒体 + 创建卡片，无需等待音频生成。
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

> **导出模式**：音频并发已足够快（~30s），直接前台运行即可。

```bash
<skill_dir>/.venv/bin/python -u <skill_dir>/generate_apkg.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -o ./<book_title_sanitized>_vocab.apkg \
  -v
```

**同步超时处理：**
- 正常完成 → 展示同步结果
- 超时退出（exit 124）→ 告知用户：「同步脚本超时。可能原因：AnkiConnect 响应慢或网络不畅。重试即可。」
- 非零退出码 → 打印 stderr，告知具体错误

**模式判断逻辑：**
- 用户说"同步/添加到 Anki" → 同步模式
- 用户说"导出/生成文件" → 导出模式
- 都不明确 → 检查 AnkiConnect：可达则同步，不可达则导出（并提示可安装 AnkiConnect）

#### 同步模式详情（sync_anki.py）

1. Step 3.5 (`--prefetch`): 并发生成全部音频 → 保存到临时目录 + manifest.json → 打印 `AUDIO_DIR=<path>`
2. Step 4 (`--audio-dir <dir>`): 从目录加载预生成音频 → 连 AnkiConnect → 查已有卡片 → 上传媒体 → 添加新卡片
3. 对每个词调用 `lemmatize_word()` 还原为原形 → 用原形构建 WordId、卡片词、音频文件名
4. **单词音频优先级**：JSON IPA（Claude 提供）→ SSML 合成 / Free Dict API 真人录音 → API IPA + Edge TTS + SSML → Edge TTS 裸词
5. **例句音频**：Edge TTS 朗读
6. **已有卡片完全不动**，保留复习进度和调度数据
7. **更新 meta manifest 卡片**：将本次 `excluded` 单词合并入元数据卡片（`WordId = __META__{bookId}`），卡片暂停（不参与复习），下次同步优先读取

牌组名自动从 JSON 推导：`"{title} ({author})"`。额外参数：`--deck "自定义"`、`--dry-run`、`--no-audio`。

#### 导出模式详情（generate_apkg.py）

1. 对每个词同样 `lemmatize_word()` 还原为原形
2. 单词音频：JSON IPA → SSML / Free Dict API → Edge TTS + SSML fallback
3. 例句音频：Edge TTS 朗读
4. 打包 `.apkg` 文件（音频嵌入）

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
| 不认识的书 | 如实告知无法回忆真实例句，提供词典例句替代方案 |
| 超过 50 个单词 | Claude 直接生成全部内容 + 并发音频（8 线程），一次写入 JSON |
| 脚本运行失败 | 检查依赖安装、网络连接，打印错误信息 |
| 词典 API 不可用 | 脚本自动 fallback 到 Edge TTS + SSML，无音频时生成纯文本版本 |
| `WEREAD_API_KEY` 未设置 | 提示用户设置：`export WEREAD_API_KEY=<your-key>` |
| AnkiConnect 不可达 | 提示启动 Anki 并安装 AnkiConnect 插件后重试；fallback 到导出 .apkg |
| 模型不在 Anki 中 | 提示先导入一次 .apkg 建立模型，再进行同步 |
| 牌组中全是新词 | 全部添加，和首次导出效果一样 |
| 同步脚本超时 | 提示原因（网络慢/词多/Anki 响应慢），建议 `--no-audio` 或分批 |
| 没有新划线生词 | 直接告知用户「没有新的划线生词」，流程自动结束 |

## 输出

**导出模式：**
- 最终交付：`.apkg` 文件路径
- 告知用户导入方式："在 Anki 中 File → Import 导入此文件即可"

**同步模式：**
- 打印新增/跳过的单词数量
- 用户直接在 Anki 中看到新卡片出现
- 复习进度完整的牌组不受影响

## 脚本清单

| 脚本 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `utils.py` | 共享工具模块 | — | safe_filename, fetch_word_data, lemmatize_word, edge_tts_bytes/file, 常量 |
| `generate_apkg.py` | 生成 .apkg 文件 | JSON → Free Dict API + Edge TTS + SSML | `.apkg` 文件 |
| `sync_anki.py` | 增量同步到 Anki | JSON + AnkiConnect | 直接添加卡片到 Anki |
| `ankiconnect.py` | AnkiConnect 客户端模块 | (内部使用) | AnkiConnect API 封装 |
| `coca_lookup.py` | COCA 20000 高频词查询 — 直接 set 查找 + lemminflect/后缀剥离兜底做派生归一（`indulgently`→`indulgent`） | 单词 → set 查找 + lemminflect + 后缀剥离 | 是否在 COCA 前 20000 词中 |
| `coca_20000.txt` | COCA 20000 词表数据 | — | 17,640 个唯一 lemma |

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译），Python 做机械工作（HTTP、TTS、打包、同步）
- **过滤前置**：Anki 去重和 COCA 频次检查在生成内容**之前**完成，避免浪费 Claude 精力。Anki 去重先于 COCA：已在牌组中的词不受 COCA 频次变化影响
- **音频并发**：多线程（8 workers）并发下载音频（Step 3.5），将音频生成压缩到秒级
- **确认前置音频**：音频在确认前预下载（`--prefetch`），确认后秒级同步（`--audio-dir`），用户不被阻塞
- **原形归一（两层分工）**：Step 1d `lemmatize_word()` 仅处理**屈折变化**（-ing/-ed/-s），不碰派生词（peaceful 不动），用于去重——确保 `pondered`+`ponder` 在管道入口合并为同一原形。Step 1f COCA 的 `in_coca()` fallback（lemminflect + 后缀剥离）处理**派生归一**（`indulgently`→`indulgent`、`resentfulness`→`resentful`），用于频次匹配——因为 COCA 20000 只收录基础词，不收录所有派生形式。两层互补，各司其职
- **bookId 桥接**：Anki 卡片 WordId `{lemma}_{bookId}` 天然包含 bookId，用于精确关联微信读书，替代不可靠的书名匹配
- **一次性确认**：整个流程仅在最终同步前确认一次，中间步骤不打断
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范；Python 脚本间提取共享 `utils.py` 消除重复代码
- **故障降级**：音频获取失败不阻塞整体流程；同步超时有明确提示和建议
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响

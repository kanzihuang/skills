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
> **确认策略：整个流程仅在 Step 4（同步/导出前）进行一次用户确认。其他步骤仅输出进度，不询问。**

### Step 0: 前置检查（含 Anki 牌组 bookId 桥接）

在开始任何 API 调用之前，先检查环境并建立 Anki ↔ 微信读书的 bookId 桥接。

**0a. 检查环境变量：**

```bash
[ -n "$WEREAD_API_KEY" ] || echo "MISSING"
```

若未设置 → 提示 `export WEREAD_API_KEY=<你的 key>`，终止。

**0b. 检查 AnkiConnect 可达性并建立 bookId 映射：**

```bash
curl -s http://localhost:8765 -d '{"action":"deckNamesAndIds","version":6}'
```

若可达 → 对每个使用 "Vocabulary Card (WeRead)" 模型的牌组，取一张卡片的 `WordId` 字段（格式 `{lemma}_{bookId}`），解析出 `bookId`。形成映射表：

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
  - 走完整搜索流程：`/store/search` → 选书 → `/book/info` → `/book/bookmarklist`
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

**1d. 筛选与原形去重（自动，不询问用户）：**

- 过滤非单词划线（整句、长段落、纯数字/符号）
- 调用 `lemmatize_word()` 将所有词还原为原形
- 按原形去重：同一原形的不同词形（如 `pondered` + `ponder`、`Abruptly` + `abruptly`）合并为一个词条，保留书中出现的代表词形
- 按原形字母排序
- 输出汇总行：`划线 X 条 → 原形去重 Y 个`

### Step 2: Anki 去重 + COCA 筛选（基于原形，生成内容之前，不询问用户）

> 此步骤在 Claude 做任何知识工作**之前**完成，仅做机械过滤。输入为 Step 1d 去重后的原形列表。
> 先查 Anki（确定信号），再查 COCA（概率信号）——已学过的词直接跳过，无需频次判断。

**2a. Anki 已有卡片对比：**

若 AnkiConnect 可达 → 查询目标牌组已有卡片。WordId 格式为 `{lemma}_{bookId}`，用原形列表精确匹配已在牌组中的词，直接跳过。

**2b. COCA 20000 批量检查（以原形查询）：**

```bash
python3 <skill_dir>/coca_lookup.py word1 word2 word3 ...
```

输出格式：`word\tTrue/False\tdetail`。不在 COCA 20000 中的单词直接排除，记录原因。

**2c. 输出汇总（仅数字，不确认）：**

```
划线 X 条 → 原形去重 Y 个 → Anki 已有 A 个 → COCA 排除 B 个 → 待生成内容 C 个
```

> COCA 查本地文本文件（毫秒级），Anki 查 localhost（毫秒级），每次实时查询即可，无需缓存。

### Step 3: 生成内容（Claude 知识工作，范围收窄）

仅对 Step 2 筛出的 C 个单词生成内容。对每个单词提供：

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 生词（书中出现的表面词形，脚本建卡用原形，已在 Step 1d 做过原形归一） | `pondered` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹 | `I <b>pondered</b> deeply, then, over the adventures of the jungle.` |
| `ipa` | IPA 音标（如已知；否则留空由脚本自动获取） | `/ˈpɒndər/` |
| `definition_cn` | 在该书上下文中的中文释义 | `沉思，深思` |
| `translation_cn` | 整句的中文翻译（遵循翻译原则） | `我于是对丛林中的冒险深深思索起来。` |

**例句规则（不变）：**
- 必须是书中真实句子，不是词典通用例句
- 如果 Claude 对某本书不够熟悉，无法回忆真实句子 → 如实告知用户，并提供词典例句作为替代
- 句子中出现的生词形式可能不同于原形（如 `straying` vs `stray`），用 `<b>` 包裹书中实际出现的词形
- 句子应完整、有语境，不是片段

**翻译原则：**

> 准确、自然、可追溯。每个关键词汇在中文里要有对应，让学习者能从句子的中文字面反推出英文结构。不要逐字死译，也不要重新创作。

- **关键词映射可追溯**：`absence of reproaches` → "没有一句责备的话"（`absence`→"没有"、`reproaches`→"责备的话"），而不是"毫无责备之意"（丢失了 `absence` 的映射）
- **句式按中文习惯调整**：英文的代词、从句、被动语态大胆打破，换成中文流水句。但词义不走样
- **动词优先选用与英文义项直接对应的词**：`intimated` → "暗示"（而非"婉转地表示"），`linger` → "徘徊"（而非"流连"），确保学习者能根据中文反查英文原词
- **不要重新创作**：翻译的目的是辅助理解英文原句，不是独立的中文美文

**IPA 规则：**
- 若知道该词在上下文中的正确 IPA → 填写。脚本会直接用 SSML 合成音频，跳过 Free Dictionary API
- 若不确定或词无歧义 → 留空 `""`，脚本自动从 Free Dictionary API 获取
- 特别对同形异音词（heteronym，如 `intimate` 形容词 /ˈɪntɪmət/ vs 动词 /ˈɪntɪmeɪt/），必须根据释义填入正确 IPA

**释义审查：**
- 在 COCA 表中的单词，判断释义是否为罕见用法（古英语义、专业术语、已淘汰的表达）。若罕见 → 不收录
- 若书中没有合适的例句 → 不收录

**完成后：**构建 JSON 写入 `/tmp/vocab-anki-input-<bookId>.json`：
- `book_title` 和 `book_author` 来自 Step 1 的解析结果（已有牌组则来自牌组名，否则来自微信读书 API）
- `book_id` 为微信读书 bookId
- `ipa` 可为空（脚本自动从 Free Dictionary API 获取），若填写则脚本用 SSML 合成音频
- `excluded` 数组记录未收录的单词及原因
- **此步骤不展示样卡，不询问用户**

### Step 4: 最终确认 + 同步/导出（唯一确认点）

**4a. 展示最终汇总（仅展示本次新变化）：**

- **新增排除**：本轮 COCA 检查中新发现不在表中的词（单词 + 原因）
- **本次新增**：将同步的单词列表（仅单词名，不展示样卡）
- Anki 已有的词仅一句话带过数量，不列出

**4b. 空跑判定：**

若本次新增为空 **且** 新增排除为空 → 直接回复「没有新的划线生词」，终止流程，**不询问用户**。

**4c. 唯一确认：**

展示汇总后，仅问一次：「确认同步？」（或导出模式下「确认导出？」）。

**4d. 执行（带超时）：**

先创建 venv 并安装依赖：

```bash
python3 -m venv /tmp/vocab-anki-venv
/tmp/vocab-anki-venv/bin/pip install -q -r <skill_dir>/requirements.txt
```

**同步模式——带 120 秒超时：**

```bash
timeout 120 /tmp/vocab-anki-venv/bin/python <skill_dir>/sync_anki.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -v
```

**导出模式：**

```bash
/tmp/vocab-anki-venv/bin/python <skill_dir>/generate_apkg.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -o ./<book_title_sanitized>_vocab.apkg \
  -v
```

**同步超时处理：**
- 正常完成 → 展示同步结果
- 超时退出（exit 124）→ 告知用户：「同步脚本超时（120s）。可能原因：网络慢（音频下载卡住）、单词过多、AnkiConnect 响应慢。可尝试加 `--no-audio` 跳过音频，或分批处理。」
- 非零退出码 → 打印 stderr，告知具体错误

**模式判断逻辑：**
- 用户说"同步/添加到 Anki" → 同步模式
- 用户说"导出/生成文件" → 导出模式
- 都不明确 → 检查 AnkiConnect：可达则同步，不可达则导出（并提示可安装 AnkiConnect）

#### 同步模式详情（sync_anki.py）

1. 连接 AnkiConnect（`localhost:8765`）
2. 对每个词调用 `lemmatize_word()` 还原为原形 → 用原形构建 WordId、卡片词、音频文件名
3. 查找目标牌组已有卡片（同时匹配原形 WordId 和原文 WordId，兼容旧卡片）→ 仅对新词处理
4. **单词音频优先级**：JSON IPA（Claude 提供）→ SSML 合成 / Free Dict API 真人录音 → API IPA + Edge TTS + SSML → Edge TTS 裸词
5. **例句音频**：Edge TTS 朗读（上下文自然消歧）
6. 上传音频到 Anki 媒体库 → 添加新卡片
7. **已有卡片完全不动**，保留复习进度和调度数据

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
| 没有划线 | 提示："这本书暂无划线笔记。先在微信读书中标记生词后再试。" |
| 划线全是整句 | 提示："划线看起来是完整句子而非生词。仍然可以生成牌组，是否继续？" |
| 不认识的书 | 如实告知无法回忆真实例句，提供词典例句替代方案 |
| 超过 50 个单词 | 建议分批生成（每批 ≤50），或让用户筛选 |
| 脚本运行失败 | 检查依赖安装、网络连接，打印错误信息 |
| 词典 API 不可用 | 脚本自动 fallback 到 Edge TTS + SSML，无音频时生成纯文本版本 |
| `WEREAD_API_KEY` 未设置 | 提示用户设置：`export WEREAD_API_KEY=<your-key>` |
| AnkiConnect 不可达 | 提示启动 Anki 并安装 AnkiConnect 插件后重试；fallback 到导出 .apkg |
| 模型不在 Anki 中 | 提示先导入一次 .apkg 建立模型，再进行同步 |
| 牌组中全是新词 | 全部添加，和首次导出效果一样 |
| 同步脚本超时（120s） | 提示原因（网络慢/词多/Anki 响应慢），建议 `--no-audio` 或分批 |
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
| `coca_lookup.py` | COCA 20000 高频词查询 | 单词 → lemminflect + 后缀剥离 | 是否在 COCA 前 20000 词中 |
| `coca_20000.txt` | COCA 20000 词表数据 | — | 17,640 个唯一 lemma |

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译），Python 做机械工作（HTTP、TTS、打包、同步）
- **过滤前置**：COCA 频次检查和 Anki 去重在生成内容**之前**完成，避免浪费 Claude 精力
- **原形归一**：去重和筛选阶段即提前还原原形（`bewildered`→`bewilder`），确保同一原形的不同词形（如 `pondered` + `ponder`）在管道入口就合并，不会生成重复卡片。卡片词、WordId、API 查询均用原形，例句保留原文词形。仅处理屈折变化（-ing/-ed/-s），派生词（peaceful）不动
- **bookId 桥接**：Anki 卡片 WordId `{lemma}_{bookId}` 天然包含 bookId，用于精确关联微信读书，替代不可靠的书名匹配
- **一次性确认**：整个流程仅在最终同步前确认一次，中间步骤不打断
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范；Python 脚本间提取共享 `utils.py` 消除重复代码
- **故障降级**：音频获取失败不阻塞整体流程；同步超时有明确提示和建议
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响

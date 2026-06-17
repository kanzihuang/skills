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

### Step 0: 前置检查

在开始任何 API 调用之前，先检查环境：

```bash
# 检查 WEREAD_API_KEY 是否已设置
[ -n "$WEREAD_API_KEY" ] || echo "MISSING"
```

- 若未设置，提示用户：`export WEREAD_API_KEY=<你的 key>`，然后终止。
- 若已设置，继续。

### Step 1: 获取划线

通过 weread API gateway 获取用户在某本书中的所有划线：

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Content-Type: application/json
```

**1a. 搜索书籍获取 bookId：**

```json
{"api_name": "/store/search", "keyword": "<书名>", "scope": 10, "count": 5, "skill_version": "1.0.3"}
```

搜索结果处理：

- 若只有一个结果 → 直接使用。
- 若多个版本 → **并行检查所有英文版（标题含"英文"、"English"、"双语"）的划线数量**，只展示有划线内容的版本给用户选择。若所有版本均无划线，告知用户并终止。
- 划线最多的版本排在前面，标注划线数。

**1b. 获取书籍信息：**

```json
{"api_name": "/book/info", "bookId": "<bookId>", "skill_version": "1.0.3"}
```

从中提取 `title` 和 `author`，作为牌组名称的一部分。

**1c. 获取划线内容：**

```json
{"api_name": "/book/bookmarklist", "bookId": "<bookId>", "skill_version": "1.0.3"}
```

回包中的 `updated[]` 数组包含所有划线，每条有 `markText`（划线文本）、`chapterUid`（章节 UID）、`createTime`。`chapters[]` 提供章节标题。

**1d. 筛选和展示：**

- 过滤掉非单词类划线（如整句、长段落、纯数字/符号）
- 去重（大小写不敏感）
- 按字母排序后展示给用户确认
- 展示格式：编号列表，显示单词、所属章节、标记日期
- 问用户是否全部使用，或需要筛选/增减

### Step 2: 生成内容（Claude 知识工作）

对每个确认的生词，提供以下内容：

| 字段 | 说明 | 示例 |
|------|------|------|
| `word` | 生词（保持原形） | `pondered` |
| `sentence` | 书中含该词的完整句子，生词用 `<b>…</b>` 包裹 | `I <b>pondered</b> deeply, then, over the adventures of the jungle.` |
| `ipa` | IPA 音标（如已知；否则留空由脚本自动获取） | `/ˈpɒndər/` |
| `definition_cn` | 在该书上下文中的中文释义 | `沉思，深思` |
| `translation_cn` | 整句的中文翻译 | `我于是对丛林中的冒险深深思索起来。` |

**例句规则：**
- 必须是书中真实句子，不是词典通用例句
- 如果 Claude 对某本书不够熟悉，无法回忆真实句子 → 如实告知用户，并提供词典例句作为替代
- 句子中出现的生词形式可能不同于原形（如 `straying` vs `stray`），用 `<b>` 包裹书中实际出现的词形
- 句子应完整、有语境，不是片段

**释义审查：**
- 判断该词在书中的释义是否为**罕见用法**（如古英语义、专业术语、已淘汰的表达）
- 若释义罕见 → 尝试换个书中例句，看不同上下文是否有常见释义。仍无常见释义 → **不收录**
- 若书中没有合适的例句 → **不收录**
- 判断依据：释义是否对这个水平的学习者有实际价值。罕见用法背了也不会遇到，反而干扰记忆

**内容生成完后：**
1. 展示 2-3 个样卡预览给用户确认
2. 列出未收录的单词，逐个说明原因（如"罕见古英语用法"、"书中无完整例句"）

### Step 3: 选择交付模式

生成 JSON 后，根据用户语境和可用性选择模式：

**默认逻辑：**
1. 如果用户明确说"同步到 Anki"或"添加到我的 Anki" → 用同步模式
2. 如果用户说"生成牌组文件"或"导出" → 用导出模式
3. 都不明确时，先检查 AnkiConnect 是否可用（运行 `curl -s http://localhost:8765` 看是否有回应），可用则用同步模式，不可用则导出 `.apkg` 并提示安装 AnkiConnect 可支持增量同步

**构建 JSON（两种模式共用）：**
- `book_title` 和 `book_author` 来自 `/book/info` 的返回值
- `book_id` 为微信读书 bookId，用于生成 `WordId = "{word}_{bookId}"` 实现同词跨书独立
- `ipa` 可以为空字符串，脚本会自动从 Free Dictionary API 获取
- 将 JSON 写入 `/tmp/vocab-anki-input-<bookId>.json`

#### 模式 A: 导出 .apkg（generate_apkg.py）

适用于：首次创建牌组、分享给他人、Anki 未运行时

```bash
python3 -m venv /tmp/vocab-anki-venv
/tmp/vocab-anki-venv/bin/pip install -q -r <skill_dir>/requirements.txt
/tmp/vocab-anki-venv/bin/python <skill_dir>/generate_apkg.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -o ./<book_title_sanitized>_vocab.apkg \
  -v
```

脚本会：
1. 对每个单词调用 Free Dictionary API 获取 IPA + 发音音频
2. API 无结果时 fallback 到 gTTS
3. 用 gTTS 生成例句朗读
4. 打包为 `.apkg` 文件，音频嵌入其中

#### 模式 B: 同步到 Anki（sync_anki.py）

适用于：Anki 正在运行、已安装 AnkiConnect 插件、需增量更新

**同步流程：**
1. 连接 AnkiConnect（`localhost:8765`）
2. 查找目标牌组中已有的卡片 → 提取已存在的 WordId 字段（`{word}_{bookId}`）
3. 对比输入 JSON 中的 WordId → 找出真正的新词
4. **仅对新词**生成音频并上传到 Anki 媒体库
5. 添加新卡片到目标牌组，带上音频引用
6. **已有卡片完全不动**，保留复习进度和调度数据

```bash
python3 -m venv /tmp/vocab-anki-venv
/tmp/vocab-anki-venv/bin/pip install -q -r <skill_dir>/requirements.txt
/tmp/vocab-anki-venv/bin/python <skill_dir>/sync_anki.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -v
```

牌组名自动从 JSON 的 `book_title` 和 `book_author` 推导（`"{title} ({author})"`），与 `generate_apkg.py` 保持一致。也可手动指定 `--deck "自定义牌组名"`。

额外参数：
- `--dry-run`：只显示会添加哪些新词，不实际添加
- `--no-audio`：跳过音频生成和上传（纯文本卡片）

**同步输出示例：**
```
Connecting to AnkiConnect...
  Deck: "The Little Prince (Antoine de Saint-Exupéry)"
  Model: Vocabulary Card (WeRead)

Querying existing cards in deck...
  Found 28 existing cards

  New words to add: 5
  Already in deck: 28

Generating audio for 5 new words...
Uploading 10 media files...
Adding 5 new cards to Anki...

==================================================
Sync complete for "The Little Prince"
  New cards added:  5
  Already in deck:  28
  Media uploaded:   10
==================================================
```

**学习记录保护机制：**
- 同步只添加新卡片（`addNotes`），从未修改或删除已有卡片
- Anki 根据 `modelName` + 字段内容进行重复检测（相同 Word 字段值不会重复添加）
- 已有卡片的学习进度、复习间隔、到期时间全部不变
- 同步后用户在 Anki 中直接可以开始背诵新词，之前背过的词不受影响

#### 模式判断流程图

```
用户说"同步/添加到Anki" → 同步模式 (sync_anki.py)
用户说"导出/生成文件" → 导出模式 (generate_apkg.py)
都没说 → curl localhost:8765
        有响应 → 同步模式
        无响应 → 导出模式 + 提示可安装 AnkiConnect
```

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
| 词典 API 不可用 | 脚本自动 fallback 到 gTTS，无音频时生成纯文本版本 |
| `WEREAD_API_KEY` 未设置 | 提示用户设置：`export WEREAD_API_KEY=<your-key>` |
| AnkiConnect 不可达 | 提示启动 Anki 并安装 AnkiConnect 插件后重试；fallback 到导出 .apkg |
| 模型不在 Anki 中 | 提示先导入一次 .apkg 建立模型，再进行同步 |
| 牌组中全是新词 | 全部添加，和首次导出效果一样 |

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
| `generate_apkg.py` | 生成 .apkg 文件 | JSON → Free Dict API + gTTS | `.apkg` 文件 |
| `sync_anki.py` | 增量同步到 Anki | JSON + AnkiConnect | 直接添加卡片到 Anki |
| `ankiconnect.py` | AnkiConnect 客户端模块 | (内部使用) | AnkiConnect API 封装 |

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译），Python 做机械工作（HTTP、TTS、打包、同步）
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范
- **故障降级**：音频获取失败不阻塞整体流程，尽可能生成可用牌组
- **增量安全**：同步模式只添加不修改，保留学习记录不受影响

---
name: vocab-book
description: >
  Extract vocabulary from any English book's full text, generate Anki
  flashcard decks with BNC/COCA frequency banding via AnkiConnect.
  Does NOT require WeRead (微信读书). Use when user says "全文制作",
  "全量词汇", "按词族等级", "词频范围", "全文", "vocabulary from
  entire book", "all words from this book", or specifies a book
  text file/URL directly. Claude handles knowledge work (sentences,
  translations), Python scripts handle filtering, audio, and sync.
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
| 章节选择 | 无 | 无 |
| Anki 去重 | 同书去重 | 无（一次性，UUID 后缀隔离） |

## 前置条件

- Python 3 + venv（脚本自动创建并安装依赖）
- Anki 正在运行 + [AnkiConnect 插件](https://ankiweb.net/simplified/info/2055492159) 已安装
- 书籍文本文件（用户提供路径 / 可下载的 URL）

> **云主机/远程环境**：若 Claude Code 在远程而 Anki 在本地，需 SSH 反向隧道：
> ```bash
> ssh -R 8765:localhost:8765 user@remote-host
> ```

## 工作流

### Step 0: 确认需求

仅确认 BNC/COCA 词族等级范围（用户未指定时提问）。

COCA 范围意图解析：

| 用户表达 | 解析结果 | `--basic-range` |
|----------|---------|-----------------|
| "等级 3-10" | Level 3-10 | `3-10` |
| "排除前3级" | 排除 Level 1-3 | `4-25` |
| "5级以上" | Level 5-25 | `5-25` |
| "中频词" / "中等难度" | 大致 Level 4-10 | **提问确认具体范围** |
| 未提及 | 无范围限制 | 省略 `--basic-range` |

> 1-based level: level 1 = 最高频。两端均 inclusive。

全文模式**不获取、不显示、不利用章节信息**——全书文本统一处理。
Anki 去重**不做**——每次运行独立，UUID 后缀确保不与其他牌组冲突。

### Step 1: 获取书籍文本

优先使用用户直接提供的文件路径。若无，WebSearch 书名+full text 查找公版书：

```bash
# 用户直接提供文件
cp /path/to/book.txt /tmp/<safe_title>-full.txt

# 或 curl 下载
curl -sL --max-time 60 '<URL>' -o /tmp/<safe_title>-full.txt
# 验证
head -c 500 /tmp/<safe_title>-full.txt
```

> 文件 >20KB 且包含书中实际文本。

### Step 2: 运行 filter_fulltext.py

```bash
# 确保 venv 存在
if [ ! -d <skill_dir>/.venv ]; then
    python3 -m venv <skill_dir>/.venv
    <skill_dir>/.venv/bin/pip install -q -r <skill_dir>/requirements.txt
fi

# 提取 + 过滤全文词汇
cat /tmp/<safe_title>-full.txt | \
<skill_dir>/.venv/bin/python3 <skill_dir>/filter_fulltext.py \
  --basic-range 3-10 \
  --json-out /tmp/vocab-book-filtered.json
```

脚本内流水线：
1. spaCy 健康检查：验证 spaCy + `en_core_web_sm` 可用，失败自动修复，修复失败则终止
2. 分词 + 词形还原：spaCy per-token POS 标注 → lemminflect 按 POS 通道还原
   - ADJ 比较级/最高级 (`JJR/JJS/RBR/RBS`) → lemminflect ADJ 通道
   - VERB (`VB*`) → lemminflect VERB 通道
   - NOUN (`NN*`) → lemminflect NOUN 通道
   - 其他 POS (ADJ/ADV/PROPN/…) → 保持原形
   - **VBG-amod 守卫**：VBG + `amod` 依赖关系 = 分词形容词（如 "bewildering complexity"），保持原形不还原。仅 `amod` 触发——`ROOT`/`xcomp`（动词谓语）照常还原
3. COCA 范围过滤 + 等级标注（`coca_level`: 1-25）
4. 生成 UUID 后缀（`uuid.uuid4().hex[:12]`），写入 JSON `suffix` 字段
5. JSON 输出（含 `in_coca[]`、`excluded[]`、`suffix`、`summary`）

### Steps 3.0–4: 句子匹配 / 翻译 / 内容 / 音频 / 同步

> 以下步骤与 vocab-anki 共享。详见 `<skill_dir>/lib/SHARED_WORKFLOW.md`。

关键路径（`<skill_dir>` 内 `lib/` 前缀）：
- `<skill_dir>/lib/scripts/match_sentences.py` — 机械句子匹配（Step 3.0）
- `<skill_dir>/lib/scripts/translate_deepl.py` — DeepL 翻译（Step 3.0f）
- `<skill_dir>/lib/sync_anki.py` — 音频预下载 + 同步（Step 3.5 + Step 4）

**全文模式特有**：
- `<tmp_id>` 使用 JSON 中的 `suffix` 字段（而非 bookId）
- WordId = `{lemma}_{suffix}`，音频文件 = `{lemma}_{suffix}_word.mp3` / `{lemma}_{suffix}_sent.mp3`
- 同步时自动频次分级（`compute_bands()`）：COCA 级别 → ≤5 段 → `{书名} ({作者}) - 分级词汇::{书名} ({作者}) - COCA X-Y`
- **不做 Anki 去重**（filter_fulltext.py 不连接 AnkiConnect）

## 异常处理

| 情况 | 处理 |
|------|------|
| 无法获取全文 | 告知用户，建议提供文本文件 |
| 源文本不可用 | 该批次所有单词跳过，不生成卡片 |
| spaCy 不可用 | 自动修复（安装依赖+下载模型），修复失败则终止任务 |
| 脚本运行失败 | 检查依赖安装、网络连接 |
| 音频生成失败 | 降级为纯文本卡片 |
| AnkiConnect 不可达 | 提示启动 Anki 并安装插件 |
| 同步脚本超时 | 提示原因，建议重试 |
| 没有通过 COCA 的单词 | 提示用户放宽范围或换书 |

## 输出

- 打印新增/跳过单词数量
- 用户直接在 Anki 中看到层级牌组和卡片

## 设计原则

- **零微信读书依赖**：不调用任何 WeRead API，不要求 WEREAD_API_KEY
- **UUID 后缀隔离**：每次运行生成唯一 UUID，WordId 和音频文件名永不冲突
- **一次性**：不做跨次去重，每次独立运行
- **不分章节**：全书文本统一处理
- **Claude + Python 分离**：Claude 做知识工作，Python 做机械工作
- **源文本检索替代回忆**：例句从源文本机械匹配，不依赖 Claude 记忆

---
name: vocab-anki
description: >
  Generate Anki vocabulary flashcard decks (.apkg) from WeRead (微信读书)
  English book highlights. Use when user wants to create Anki cards from their
  WeRead highlights, e.g. "/vocab-anki The Little Prince" or "为这本书的划线生词
  生成 Anki 牌组". Integrates with weread-skills for data; Claude does knowledge
  work (sentences, translations), Python script handles audio + packaging.
---

# vocab-anki — 英文书词汇 Anki 牌组生成

将微信读书英文原版书的划线生词转换为 Anki 牌组（`.apkg`），嵌入发音音频。

## 前置条件

- `weread-skills` 已安装，`WEREAD_API_KEY` 环境变量已设置
- Python 3 + venv（脚本会自动创建 venv 并安装依赖）

## 工作流

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

如果搜索到多个版本，列出让用户选择。如果只有一个结果，直接使用。

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

**释义规则：**
- 中文释义要贴合书中实际用法，不要直接搬词典
- 一词多义时（如 `fair`）要根据句子语境确定正确释义

**内容生成完后，展示 2-3 个样卡预览给用户确认。**

### Step 3: 构建 JSON 并运行脚本

**3a. 构建输入 JSON：**

```json
{
  "book_title": "The Little Prince",
  "book_author": "Antoine de Saint-Exupéry",
  "words": [
    {
      "word": "pondered",
      "sentence": "I <b>pondered</b> deeply, then, over the adventures of the jungle.",
      "ipa": "/ˈpɒndər/",
      "definition_cn": "沉思，深思",
      "translation_cn": "我于是对丛林中的冒险深深思索起来。"
    }
  ]
}
```

- `book_title` 和 `book_author` 来自 `/book/info` 的返回值
- `ipa` 可以为空字符串，脚本会自动从 Free Dictionary API 获取
- 将 JSON 写入 `/tmp/vocab-anki-input-<bookId>.json`

**3b. 确定输出路径：**

默认放在用户当前工作目录：`{book_title_sanitized}_vocab.apkg`。
书名中的特殊字符用下划线替代，空格保留或转为下划线。

示例：`The_Little_Prince_vocab.apkg`

**3c. 运行 Python 脚本：**

```bash
# 创建/复用 venv
python3 -m venv /tmp/vocab-anki-venv
/tmp/vocab-anki-venv/bin/pip install -q -r <skill_dir>/requirements.txt

# 运行生成
/tmp/vocab-anki-venv/bin/python <skill_dir>/generate_apkg.py \
  /tmp/vocab-anki-input-<bookId>.json \
  -o ./<book_title_sanitized>_vocab.apkg \
  -v
```

`<skill_dir>` 是本 SKILL.md 所在的目录路径。

脚本会：
1. 对每个单词调用 Free Dictionary API 获取 IPA + 发音音频
2. API 无结果时 fallback 到 gTTS
3. 用 gTTS 生成例句朗读
4. 打包为 `.apkg` 文件，音频嵌入其中

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

## 输出

- 最终交付：`.apkg` 文件路径
- 告知用户导入方式："在 Anki 中 File → Import 导入此文件即可"
- 如果用户有 AnkiConnect 插件，可以提示通过 AnkiConnect API 直接导入

## 设计原则

- **职责分离**：Claude 做知识工作（理解语境、翻译），Python 做机械工作（HTTP、TTS、打包）
- **不重复造轮**：划线获取复用 weread-skills 的 API 规范
- **故障降级**：音频获取失败不阻塞整体流程，尽可能生成可用牌组

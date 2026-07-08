---
name: vocab-list
description: >
  输出英文原版书全量 BNC/COCA 25000 单词表。对全文单词做屈折还原（拒绝跨词性转换）、
  BNC/COCA 25000 词族过滤、词形去重，生成干净的词汇列表。当用户说"输出《书名》单词表"、
  "导出《书名》全量词汇"、"生成《书名》词汇表"、"这本书的单词表"、
  "vocabulary list for <book>"、"word list"、"单词表"时触发。
  整合 weread-skills 搜索书籍元数据，Claude 负责获取全文，Python 脚本负责
  词形还原和 COCA 过滤。
---

# vocab-list — 英文书全量单词表

从英文原版书提取全量单词，屈折还原后过滤 BNC/COCA 25000 词族表，输出干净的词形去重列表。

## 架构

```
Claude:  知识工作 —— 搜索书籍、获取全文、展示结果
Python:  机械工作 —— 词形提取、屈折还原、COCA 过滤、去重
```

**脚本清单：**

| 脚本 | 用途 |
|------|------|
| `scripts/extract_vocab.py` | 从原始文本提取单词，屈折还原 + COCA 过滤 + 去重，输出 `[COCA]` / `[EXCLUDED]` 词表 |

**依赖：**
- `weread-skills` — 书籍搜索（获取 bookId、书名、作者）
- `lib/` — 共享库：`lib/lemmatize.py`（屈折还原引擎）、`lib/coca.py`（BNC/COCA 词族查找，Nation 2017）、`lib/data/bnc_coca/basewrd1.txt`–`basewrd25.txt`（词族数据，25 个独立文件）
- Python 包：`lemminflect`

## 前置条件

- `WEREAD_API_KEY` 环境变量已设置
- `lemminflect` 已安装（`pip3 install lemminflect`）
- `weread-skills` 已安装

## 工作流

### Step 1: 解析书名

用户输入书名（中文或英文）→ 使用 weread-skills 的 `/store/search` 搜索：

```bash
curl -s -X POST "https://i.weread.qq.com/api/agent/gateway" \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/store/search","keyword":"<书名>","count":10,"skill_version":"1.0.3"}'
```

从中选择英文版：
- 优先选 `translator` 为空（原版英文）
- 有多个英文版时，列出让用户选择
- 获取 `bookId`、`title`、`author`

### Step 2: 获取全文

**WeRead API 不提供章节正文**，需要从外部源获取。

搜索策略（按优先级）：
1. **Internet Archive** — `WebSearch: "<English title> <author> full text archive.org"`
2. **Project Gutenberg** — `WebSearch: "<English title> <author> gutenberg.org"`
3. **Standard Ebooks** — `WebSearch: "<English title> standardebooks.org"`
4. **esl-bits.eu 等教育站点** — `WebSearch: "<English title> full text chapter 1"`
5. **WebFetch 逐章获取** — 最后手段（有字数限制，仅适合短书）

下载方式：
```bash
curl -sL --max-time 60 '<URL>' -o /tmp/<safe_title>.txt
```

验证：文件 > 20KB，包含实际书本章节文本。

**无法获取全文时**：告知用户当前无法找到该书的免费全文，建议用户提供文本文件。

### Step 3: 清洗文本（可选）

如果源文本包含页眉页脚（如 "For English Language Learners..."、"Table of Contents >>"、章节标记等），先清洗：

```bash
python3 scripts/extract_vocab.py --clean < /tmp/<book>.txt > /tmp/<book>_clean.txt
```

如果源文本已经是纯净的（如 Gutenberg 纯文本），跳过此步。

### Step 4: 提取词汇

```bash
# 基础提取
python3 scripts/extract_vocab.py < /tmp/<book>_clean.txt

# 排除 COCA 频率排名 前 N 个最基础词汇（如 --exclude-basic 2000）
python3 scripts/extract_vocab.py --exclude-basic 2000 < /tmp/<book>_clean.txt

# 只保留 COCA 频率排名 排名范围内的中频词汇（如 3001-10000）
python3 scripts/extract_vocab.py --basic-range 3001-10000 < /tmp/<book>_clean.txt

# 组合使用：排除 top 3000，并限制在 3001-10000 范围
python3 scripts/extract_vocab.py --exclude-basic 3000 --basic-range 3001-10000 < /tmp/<book>_clean.txt
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--clean` | 去除常见页眉页脚（esl-bits 等教育站点的导航文本） |
| `--exclude-basic N` | 排除 COCA 频率排名 中前 N 个最频繁的基础词 |
| `--basic-range M-N` | 只保留 COCA 频率排名 排名在 M–N 范围内的词汇 |

脚本内部流程：
1. 提取所有 2+ 字母的英文单词 → 小写 → 去重排序
2. 对每个不在 BNC/COCA 词族中的单词做屈折还原
3. COCA 过滤 + 词形去重
4. （可选）COCA 频率排名 频率范围过滤
5. 输出统计 + `[COCA]` 词表 + `[EXCLUDED]` 排除词表

**重要：** 脚本使用 repo 根目录的 `lib/` 共享库，运行时工作目录应为 skill 目录。

### Step 5: 展示结果

按以下格式输出：

```
## 《书名》(作者) — BNC/COCA 25000 单词表

**处理统计：**
- 原始词例 (token): ~XX,XXX
- 原始去重单词: X,XXX
- 屈折还原后: X,XXX  
- **BNC/COCA 25000 词表: X,XXX**
- 排除词: XXX

### COCA 单词表（按字母排列）

4 栏输出完整词表。

### 排除词表

不在 BNC/COCA 25000 中的单词（专有名词、低频词等）。

### 处理说明

- 屈折还原：仅处理规则/不规则屈折变化（复数 -s、过去式 -ed、分词 -ing、比较级 -er/-est），拒绝跨词性还原
- 还原示例：are→be, has→have, men→man, bought→buy
- 保留原形示例：blundering（派生形容词，不还原为 blunder）
```

## 设计原则

1. **Claude + Python 分离**：Claude 做搜索、下载、展示；Python 做机械的词形处理
2. **拒绝跨词性转换**：只做屈折还原（inflectional），不做派生还原（derivational）。`blundering` adj. 保留，不强制还原为 `blunder` v.
3. **COCA 验证一切**：所有还原结果必须在 BNC/COCA 25000 中，避免产生无效词形
4. **IRREG 绝对优先**：不规则形式优先于规则模式匹配，避免 `has→ha` 等错误
5. **单词本身在 COCA 中则保持原样**：COCA 中的高频屈折形式（如 `abandoned`）不强制还原
6. **共享 lib/ 库**：词形还原 + COCA 查找逻辑在 `lib/` 中，供 `vocab-list`、`vocab-anki` 等 Skill 共用

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 搜索不到英文版 | 列出所有搜索结果让用户选择 |
| 多个英文版本 | 列出并让用户选择，优先选原版（无译者） |
| 找不到免费全文 | 告知用户并提供替代方案（提供文本文件、手动复制章节） |
| 文本包含大量页眉页脚 | 使用 `--clean` 标志清洗，或手动编辑去除 |
| 中英对照版 | 只提取英文部分（通过字母正则 `[a-zA-Z]{2,}` 自然过滤） |
| 单词数 > 50,000 | 分批处理，每批 ~10,000 词 |
| `lemminflect` 未安装 | `pip3 install --break-system-packages lemminflect` |

## 输出示例

```
=================================================================
THE LITTLE PRINCE — FULL BNC/COCA 25000 WORD LIST
(inflectional lemmatization · 拒绝跨词性转换 · BNC/COCA 25000 · deduplicated)
Total: 1595 words
=================================================================

abandoned             able                  about                 above
abruptly              absolute              absurd                abyss
...
```

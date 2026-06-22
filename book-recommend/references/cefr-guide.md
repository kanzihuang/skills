# CEFR 词汇分级参考指南

用于根据微信读书英文划线单词评估用户英语阅读水平。

## 分级框架

| CEFR | 水平 | 词汇量 | 可读材料 | Lexile |
|------|------|--------|----------|--------|
| A1 | 入门 | ~500 | 简单句子、标签 | BR-200L |
| A2 | 基础 | ~1000-1500 | 简单短篇、日常对话 | 200L-500L |
| B1 | 中级 | ~2000-3500 | 青少年小说、简化经典 | 500L-800L |
| B2 | 中高级 | ~4000-6000 | 原版小说、非虚构 | 800L-1100L |
| C1 | 高级 | ~8000-12000 | 复杂文学、学术 | 1100L-1400L |
| C2 | 精通 | ~16000+ | 任何材料 | 1400L+ |

## 词汇分级的实用信号

Claude 根据以下综合信号判断单词级别，而非依赖固定词表：

### A2 级特征
- 高频日常词汇：amuse, confess, tragedy, ridiculous, fair, contrary
- 通常在中小学课本中出现
- 无明显文学/学术色彩

### B1 级特征
- 能理解但非最基础词汇：reputation, eternal, occupied, puzzled, condemn, poetic, monarch, linger, endure, precious, vanity, restrain, blossom, reassure, meditation, discipline
- 日常阅读中出现频率中等
- 具有一定描述性但不专业

### B2 级特征
- 文学/新闻常见但口语不常用的词汇：intoxicated, stately, scorned, lugubrious, dejection, conceited, forsaken, etiquette, majestic, bewildered, reproaches, adornment, coquettish, relentlessly, moralist, impenetrable, reverie, apparition, disheartened, pondered
- 抽象概念、精确描述
- 高频出现在经典文学和非虚构写作中

### C1 级特征
- 低频文学/学术词汇：ephemeral, balderdash, impregnable, thriftily, insubordination, consumingly, ermine, mantle, peevishly
- 古雅或诗歌用词：blest, clad, abodes
- 专业领域术语
- 高级派生词

## 水平判定规则

### 单一书籍判定
1. 统计各 CEFR 级别的划线单词占比
2. **核心判定**：
   - B1 词占 30%+ 且 C1 词 < 10% → A2 水平（阅读比自身水平高的材料）
   - B1 词 25-40%、B2 词 30-45% → B1 水平
   - B2 词占 40%+ 且 C1 词 15-30% → B2 水平
   - C1 词占 30%+ → C1 水平
3. **辅助信号**：
   - 大量基础词（amuse, confess 等）标记 → 偏向 A2-B1
   - 划线密度（划线数/总字数）> 2% → 偏低水平
   - 划线密度 < 0.5% → 偏高水平
   - 文学描写词占比高 → 可能低估（这些词即使是 B2-C1 读者也会标记）
4. **最终判定**：取核心判定 + 辅助信号的加权判断，给出最可能的 CEFR 区间

### 多书籍判定
- 优先使用最近读完的英文书
- 若有多本，取词汇难度的加权平均
- 阅读进度 < 50% 的书降低权重（可能中途放弃因太难）

## 生词类型分析

除了级别外，分析生词类型有助于精准推荐：

| 类型 | 信号 | 推荐方向 |
|------|------|----------|
| 文学描写词居多 | lugubrious, voluminous, stately, coquettish | 现代小说、非虚构 |
| 情感/心理词居多 | dejection, resentfulness, remorse, conceited | 人物驱动小说 |
| 高级副词居多 | indulgently, peevishly, consumingly | 需要更多 B1-B2 普通读物 |
| 古雅形式多 | blest, clad, abodes, apparition | 这是正常现象，换现代作品即可 |
| 基础词仍有标记 | amuse, confess, fair | 先巩固基础，选 A2-B1 材料 |

## 推荐难度映射

| 用户水平 | 推荐主力难度 | 挑战难度 | 应避免 |
|----------|------------|---------|--------|
| A2 | A2-B1 双语版/书虫 | B1 简写版 | 原版经典 |
| B1 | B1 原版现代小说 | B2 中短篇 | C1 经典文学 |
| B2 | B2 原版各类 | B2+ 经典 | — |
| C1 | C1 任意 | — | — |

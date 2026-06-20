# vocab-anki

将微信读书英文原版书的划线生词通过 AnkiConnect 直接同步到 Anki，嵌入发音音频。

## 快速开始

```
为我生成《小王子》划线生词的 Anki 牌组
同步到 Anki
```

前置条件：

- [weread-skills](https://github.com/Tencent/WeChatReading) 已安装，`WEREAD_API_KEY` 已设置
- Python 3 + venv（脚本自动创建并安装依赖）
- Anki 运行中 + [AnkiConnect](https://ankiweb.net/shared/info/2055492159) 插件

## 工作流

```
微信读书划线 → 获取划线数据 → 过滤流水线 → Claude 生成例句+释义+IPA → 脚本生成音频 → 同步到 Anki
```

- **Claude**：知识工作 — 回忆书中真实例句，提供中文释义、翻译和 IPA 音标
- **Python**：机械工作 — 词形还原、Anki 去重、COCA 频次检查、Edge TTS 音频合成、同步

## 卡片样式

采用 COCA-English 牌组同款设计，Georgia 衬线字体，自适应暗色模式，响应式布局。

## 设计原则

- **职责分离**：Claude 做知识工作，Python 做机械工作
- **原形优先去重（两层分工）**：先还原原形再统一去重/筛选，同原形的不同词形不会生成重复卡片。`lemmatize_word()` 仅处理屈折变化（pondered→ponder、crammed→cram），不碰派生词；COCA `in_coca()` fallback 做派生归一（indulgently→indulgent）。两层均用 `len(lemma) < len(word)` 防跨词性误判（abode n.↛abide v.），互补统一
- **跨书独立**：`WordId = {lemma}_{bookId}` 作为首字段，不同书中的同一单词互不冲突
- **IPA 零网络依赖**：Claude 从训练数据直接生成 IPA 用于卡片显示，单词音频由 Edge TTS 默认发音生成，无外部 API 依赖
- **故障降级**：音频生成失败不阻塞卡片创建（Edge TTS 不可用时自动跳过音频）
- **增量安全**：同步只添加不修改，已有卡片的学习进度完全保留
- **逐词超时**：每词 30s 超时（`--word-timeout`），超时跳过继续；连续 3 词超时中断同步
- **牌组名自动匹配**：`{书名} ({作者})`

## 脚本

| 脚本 | 用途 |
|------|------|
| `sync_anki.py` | 增量同步到 Anki，仅添加新词。支持 `--word-timeout` 逐词超时，`--dry-run` |
| `ankiconnect.py` | AnkiConnect JSON-RPC 客户端 |
| `filter_pipeline.py` | 合并过滤流水线：lemmatize → Anki 去重 → COCA 检查 |
| `utils.py` | 共享工具：lemmatize_word, edge_tts_bytes/file, safe_filename |
| `coca_lookup.py` | COCA 20000 高频词查询 |
| `coca_20000.txt` | COCA 20000 词表数据（17,640 个唯一 lemma） |

## 许可证

Apache License 2.0

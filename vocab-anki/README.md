# vocab-anki

将微信读书英文原版书的划线生词转换为 Anki 牌组，嵌入发音音频。

## 两种模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| 导出 `.apkg` | 生成独立牌组文件，手动导入 Anki | 首次建牌组、分享给他人、Anki 未运行 |
| 同步到 Anki | 通过 AnkiConnect 增量同步，仅添加新词 | Anki 已运行、持续积累生词 |

## 快速开始

```
为我生成《小王子》划线生词的 Anki 牌组
同步到 Anki
```

前置条件：

- [weread-skills](https://github.com/Tencent/WeChatReading) 已安装，`WEREAD_API_KEY` 已设置
- Python 3 + venv（脚本自动创建并安装依赖）
- 同步模式额外需要：Anki 运行中 + [AnkiConnect](https://ankiweb.net/shared/info/2055492159) 插件

## 工作流

```
微信读书划线 → 获取划线数据 → Claude 生成例句+释义 → 脚本生成音频 → Anki 牌组
```

- **Claude**：知识工作 — 回忆书中真实例句，提供中文释义和翻译
- **Python**：机械工作 — 从 Free Dictionary API 获取 IPA/音频（Edge TTS + SSML 兜底），生成例句朗读，打包或同步

## 卡片样式

采用 COCA-English 牌组同款设计，Georgia 衬线字体，自适应暗色模式，响应式布局。

## 设计原则

- **职责分离**：Claude 做知识工作，Python 做机械工作
- **原形优先去重**：先还原原形再统一去重/筛选，同原形的不同词形不会生成重复卡片
- **跨书独立**：`WordId = {lemma}_{bookId}` 作为首字段，不同书中的同一单词互不冲突，卡片正面仍显示 `{{Word}}`
- **故障降级**：音频获取失败不阻塞卡片生成（Free Dictionary API → Edge TTS + SSML 降级）
- **增量安全**：同步只添加不修改，已有卡片的学习进度完全保留
- **逐词超时**：每词 30s 超时（`--word-timeout`），超时跳过继续；连续 3 词超时中断同步，汇总列出失败单词
- **默认进度条**：TTY 自适应进度条 `[████░░░░] P% i/N word`（终端原地覆盖，管道/捕获则逐行输出），无需 `-v`；verbose 模式额外显示音频细节和字节数
- **牌组名自动匹配**：`{书名} ({作者})`，与 `generate_apkg.py` 一致

## 脚本

| 脚本 | 用途 |
|------|------|
| `generate_apkg.py` | 生成 `.apkg` 文件，音频嵌入其中。支持 `--word-timeout` 逐词超时 |
| `sync_anki.py` | 增量同步到 Anki，仅添加新词。支持 `--word-timeout` 逐词超时，`--dry-run` |
| `ankiconnect.py` | AnkiConnect JSON-RPC 客户端 |
| `utils.py` | 共享工具：safe_filename, fetch_word_data, lemmatize_word, edge_tts_bytes/file |
| `coca_lookup.py` | COCA 20000 高频词批量查询（CLI） |
| `coca_20000.txt` | COCA 20000 词表数据（17,640 个唯一 lemma） |

## 许可证

Apache License 2.0

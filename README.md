# Claude Code Skills

Claude Code 技能合集，扩展 Claude Code 的能力边界。

## 技能列表

### [vocab-anki](vocab-anki/)

将微信读书英文原版书的划线生词转换为 Anki 学习牌组，嵌入发音音频。

- **导出模式**：生成 `.apkg` 文件，手动导入
- **同步模式**：通过 AnkiConnect 直接同步到 Anki，增量添加新词
- **原形归一**：自动将变形词还原为原形（`bewildered` → `bewilder`）建卡
- **Edge TTS + SSML**：微软免费 TTS，国内直连；支持 IPA 指定发音
- 集成 [weread-skills](https://github.com/Tencent/WeChatReading) 获取划线数据

## 安装

```bash
# 克隆仓库
git clone https://github.com/kanzihuang/skills.git

# 创建技能 symlink
ln -s $(pwd)/skills/vocab-anki ~/.claude/skills/vocab-anki
```

## 许可证

Apache License 2.0

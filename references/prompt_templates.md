# Prompt 模具索引与派发指南

本目录包含 `somark-book-epub` 在派发子智能体修润各个章节时的提示词模具与动态组装示例。

---

## 模板清单

| 模具文件 | 适用场景 | 说明 |
| :--- | :--- | :--- |
| `references/prompts/polish_chapter.txt` | 通用图书篇章排版修润 | 规范 H2/H3 层级、图注语义绑定、去噪清洗、流式段落 |

---

## 主 Agent 动态派发示例 (Map Phase)

在派发子智能体时，主 Agent 应将通用规范与本轮图书的**书型体例（Book Profile）**及**用户个性化指令**动态组装后一并下发：

```python
# 示例：主 Agent 动态拼接派发子智能体
user_extra_notes = "用户要求：过滤 CIP 版权页与定价条码，保留卷首题记。"
book_profile = "书型：多作者文集，每篇保留独立署名 <p class=\"chapter-author\">作者</p>"

prompt_content = f"""
请审阅并修润文件：{localized_md_path}
参考出版级排版规约：references/prompts/polish_chapter.txt

篇目标题：{chapter_title}
{f'篇章作者：{chapter_author}' if chapter_author else ''}

【本轮专项体例与用户要求】
{book_profile}
{user_extra_notes}

完成后直接覆盖写回原文件，并回复：[DONE] {part_name}
"""

invoke_subagent(
    TypeName="self",
    Role="Chapter Stylist",
    Prompt=prompt_content
)
```

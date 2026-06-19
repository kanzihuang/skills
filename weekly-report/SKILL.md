---
name: weekly-report
description: Generate weekly work reports from daily reports. Use when the user provides multiple days of daily work logs and wants a merged weekly summary in Markdown and HTML formats. Also trigger when the user says "周报", "weekly report", "本周日报", or provides daily reports with dates. The skill categorizes similar tasks across days, generates both .md and .html files, copies HTML to Windows clipboard, and opens the report in a browser.
---

# Weekly Report Generator

Generate a weekly work report from daily report text. The daily reports typically contain date headers like "2026年6月18日（周四）" with "今日工作总结" and "明日安排计划" sections.

## Workflow

### Step 1: Parse and Categorize

Read through all daily reports and:
1. Extract all "今日工作总结" items across all days
2. Group similar items into logical categories (e.g., 运维审计, 乐效CD, 域名备案, LDAP, 其他)
3. For each category, note which days the work occurred (e.g., "周一/三/四")
4. Identify the week range from the dates (e.g., "6.15 — 6.18")

Common categories that emerge:
- **运维审计与合规**: audit/review related items
- **乐效CD（持续交付平台）**: CI/CD platform items
- **域名与备案管理**: domain and ICP filing items
- **LDAP**: LDAP related items
- **其他工作**: miscellaneous items that don't fit above

### Step 2: Generate Markdown (.md)

Write the report in this exact format:

```
# [Week range title]

## [Category 1]
- [merged item 1]
- [merged item 2]

## [Category 2]
- ...

---

**下周重点工作计划：** [summary from 明日安排计划 patterns]
```

Rules:
- Title format: `YYYY年M月第N周工作周报（M.DD — M.DD）`
- No blank lines after `##` headings or `#` title
- Merge similar items across days, noting day ranges in parentheses like "（周一至周四）" or "（周一/三/四）"
- Use bold for sub-labels within list items: `**问题排查：**`
- Include a `---` separator before the next-week plan section

### Step 3: Generate HTML (.html)

Use this exact template with inline styles:

```html
<div style="font-size:14px">

<p style="font-size:16px;font-weight:bold">[MAIN TITLE]</p>

<p style="font-size:15px;font-weight:bold">[Category 1]</p>
<ul>
  <li>[item]</li>
</ul>

<p style="font-size:15px;font-weight:bold">[Category 2]</p>
<ul>
  ...
</ul>

<hr>

<p><strong>下周重点工作计划：</strong>[summary]</p>

</div>
```

Critical rules:
- **Never use `<h1>` or `<h2>` tags** — use `<p>` with inline styles instead
- Body text: `font-size:14px` (set on wrapper `<div>`)
- Section headings: `font-size:15px;font-weight:bold`
- Main title: `font-size:16px;font-weight:bold`
- Bold inline labels use `<strong>` tags
- Wrap everything in `<div style="font-size:14px">`

### Step 4: Save Files

Save both files to the current working directory:
- `[week-file-name].md` — Markdown version
- `[week-file-name].html` — HTML version

Naming convention: `YYYY-Www.md` / `YYYY-Www.html` (e.g., `2026-W25.md`)

### Step 5: Copy to Windows Clipboard and Open Browser

Run the bundled PowerShell script to handle both clipboard and browser:

```bash
cp [html-file] /mnt/c/Users/Public/Downloads/[html-file-name]
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File ".claude/skills/weekly-report/scripts/to-clipboard.ps1" -htmlPath "C:\Users\Public\Downloads\[html-file-name]"
```

The script copies HTML to the Windows clipboard in proper HTML clipboard format (with Version:0.9 headers and fragment markers) so it pastes directly into browser rich text editors, then opens the file in Edge for preview.

## Example

**Input (4 daily reports):**
```
2026年6月18日（周四）
今日工作总结
1. 更新运维审计报告
2. 排查乐效CD构建问题
...
明日安排计划
1. 华为云续费
...

2026年6月17日（周三）
今日工作总结
1. 华为云运维审计
2. 乐效CD运维审计
...
```

**Output:** A merged weekly report grouping items under 5 categories with day ranges, plus a consolidated next-week plan, saved as .md and .html, HTML copied to clipboard and opened in browser.

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
2. Group similar items into the following categories:
   - **CICD**: CI/CD platform items (project creation, build/deploy/environment troubleshooting, technical support)
   - **云运维**: cloud operations items (Huawei Cloud certification, domain resolution, cloud infrastructure)
   - **数据备份**: data backup items (backup reports)
   - **运维自动化**: operations automation items (automated monitoring, auto-remediation)
   - **其他工作**: miscellaneous items that don't fit above (LDAP, audits, handover, meetings)
3. Identify the week range from the dates (e.g., "6.22 — 6.26")

**Important:** If a category has no specific work items for the week, omit it from the report. Only include categories with actual content.

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
- **Do NOT include day ranges** in parentheses — the report is a summary, not a timeline
- Merge similar items across days without noting which days they occurred
- Item descriptions must be strictly based on daily report text — do not embellish or expand
- Use bold for sub-labels within list items: `**问题排查：**`
- Include a `---` separator before the next-week plan section
- Omit categories that have no work items

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
- Omit categories that have no work items

### Step 4: Save Files

Save both files to the current working directory:
- `[week-file-name].md` — Markdown version
- `[week-file-name].html` — HTML version

Naming convention: `YYYY-Www.md` / `YYYY-Www.html` (e.g., `2026-W26.md`)

### Step 5: Copy to Windows Clipboard and Open Browser

Copy the HTML file to a Windows-accessible path, then invoke the PowerShell script from WSL:

```bash
cp [html-file] /mnt/c/Users/Public/Downloads/[html-file-name]
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "\\\\wsl.localhost\\Ubuntu\\home\\agent\\github\\kanzihuang\\skills\\weekly-report\\scripts\\to-clipboard.ps1" -htmlPath "C:\\Users\\Public\\Downloads\\[html-file-name]"
```

Alternatively, copy the script to Windows first and invoke locally:

```bash
cp [html-file] /mnt/c/Users/Public/Downloads/[html-file-name]
cp skills/weekly-report/scripts/to-clipboard.ps1 /mnt/c/Users/Public/Downloads/to-clipboard.ps1
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "C:\Users\Public\Downloads\to-clipboard.ps1" -htmlPath "C:\Users\Public\Downloads\[html-file-name]"
```

Both approaches copy HTML to the Windows clipboard in proper HTML clipboard format (with Version:0.9 headers and fragment markers) so it pastes directly into browser rich text editors, then open the file in Edge for preview.

**Troubleshooting:** If `powershell.exe` is not found, use the full path `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`. On WSL 2, the bare `powershell.exe` command may not resolve without the full Windows path.

## Example

**Input (5 daily reports):**
```
2026年6月26日（周五）
今日工作总结
1. 创建乐效CD项目
2. 排查乐效CD构建问题
3. LDAP 技术支持
...
明日安排计划
1. 华为云续费
...

2026年6月25日（周四）
今日工作总结
1. 创建乐效CD项目
2. 排查乐效CD部署问题
...
```

**Output:** A merged weekly report grouping items under categories (CICD, 云运维, 数据备份, 运维自动化, 其他工作), without day range annotations, plus a consolidated next-week plan, saved as .md and .html, HTML copied to clipboard and opened in browser. Empty categories are omitted.

# analysis_report 正文页布局优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改现有 `analysis_report.pptx` 模板正文页，使场景、文件名、12 pt 单倍行距正文和主/副图区域符合已确认的均衡型布局。

**Architecture:** 直接导入现有 PPTX，编辑正文页继承的标题、正文和内容占位符，不新建演示文稿。内容占位符调整为主图上方区域和副图下方区域；正文生成时可分别填充两个图片占位符。

**Tech Stack:** PowerPoint PPTX、`@oai/artifact-tool`、模板跟随检查脚本、PNG 渲染。

---

### Task 1: Inspect the current template

**Files:**
- Inspect: `src/health_tools/templates/analysis_report.pptx`
- Create: `debug/template-body-layout/inspect-*`

- [ ] Import the template with artifact-tool and record the正文页 shape ids, placeholder types, frames, font sizes, and paragraph spacing.
- [ ] Render the正文页 before editing and verify that the current master/footer/logo remain visible.

### Task 2: Edit inherited正文 placeholders

**Files:**
- Modify: `src/health_tools/templates/analysis_report.pptx`
- Create: `debug/template-body-layout/edit-template.mjs`

- [ ] Rewrite the inherited title placeholder as a 30 pt scene title and move its frame upward without changing the master or layout relationship.
- [ ] Rewrite the inherited body placeholder as a 12 pt single-line-spaced text frame on the left.
- [ ] Replace the inherited right content placeholder with two image placeholders: main image above, shorter secondary image below, with a fixed gap and no overlap with the footer.
- [ ] Preserve the existing logo, footer, theme colors, and cover/ending slides.
- [ ] Export the edited PPTX to a temporary output and then replace the template file only after verification.

### Task 3: Verify visual and structural fidelity

**Files:**
- Inspect: `debug/template-body-layout/rendered/*.png`
- Inspect: `debug/template-body-layout/*.layout.json`

- [ ] Render the edited正文页 at full slide size.
- [ ] Confirm title is 30 pt, filename slot is 20 pt, body is 12 pt with single spacing, and images stay above the footer.
- [ ] Run template fidelity validation and record zero structural issues.
- [ ] Run slide overflow checks; if the environment cannot resolve the bundled runtime, document the exact failure and use artifact-tool exports plus layout bounds as the fallback evidence.

### Task 4: Commit the template change

**Files:**
- Commit: `docs/superpowers/specs/2026-08-19-analysis-report-body-layout-design.md`
- Commit: `docs/superpowers/plans/2026-08-19-analysis-report-body-layout.md`
- Commit: `src/health_tools/templates/analysis_report.pptx`

- [ ] Stage only the three listed files.
- [ ] Commit with `docs: optimize analysis report body layout` and the required co-author trailer.

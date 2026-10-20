# 跨平台使用边界

核对日期：2026-10-11。本技能使用标准 `SKILL.md`、相对参考链接和 Python 标准库；不依赖某个平台的 MCP、环境变量、私有工具名称或子 agent 能力。

## 命名与识别

用户已确认把最初的 `control_paper_writing` 改为 `control-paper-writing`。通用规范要求名称仅使用小写字母、数字和连字符，并与父目录一致，因此本技能目录和 YAML `name` 均为 `control-paper-writing`。[Agent Skills 规范](https://agentskills.io/specification)

`agents/openai.yaml` 只是 Codex 的界面元数据；完整业务指令均在 `SKILL.md` 与其相对引用的文件中。其他平台不读取该配置也不影响业务规则。保持默认自动发现，没有强制单独调用策略或限定工具列表。[OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)

## 按平台分发

下面是供安装时参考的目标位置，**本次创建不自动安装或修改平台配置**。复制完整目录后，名称保持一致，避免同名旧版本造成选择歧义。

| 平台 | 官方支持的常见本地位置 | 显式使用 |
| --- | --- | --- |
| Codex | 项目 `.agents/skills/control-paper-writing/`；用户 `~/.agents/skills/control-paper-writing/` | `$control-paper-writing` 或技能选择器 |
| Claude Code | 项目 `.claude/skills/control-paper-writing/`；用户 `~/.claude/skills/control-paper-writing/` | `/control-paper-writing` |
| 其他支持 Agent Skills 的 agent | 使用该平台指定的发现目录，保留整个技能目录 | 使用该平台的调用语法 |

位置和调用语法分别依据 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills) 和 [Claude Code 官方技能文档](https://code.claude.com/docs/en/skills)。具体安装版本和云端/本地环境仍需核实，本文不能保证所有 agent 版本都自动识别。

不支持自动技能发现的平台，可以显式要求 agent 读取本目录 `SKILL.md`，然后按需读取引用文件；这仅复用指令，不提供平台原生自动触发能力。

## 能力缺失时

- **无联网：** 使用用户提供文献与模板，标记未在线核验项，不伪造检索或官方来源。
- **无 Python 3.9+：** 按 project-state.md 人工核对台账与数值；不用脚本也能写作。记录未运行的检查。
- **只有 PDF/DOCX 正文：** 保留原稿，用可用工具导出 UTF-8 审查正文并核对转换结果，再运行脚本；无法导出时人工核对，明确未执行正文片段检查。脚本本身不转换这些格式。
- **无编译/渲染：** 给可编辑工作稿与图表源文件，实际分页和正式图件核验待办，不能声称已完成。
- **无文件写入：** 在对话中交付正文和精简台账；跨会话需由用户保存后提供，不假设永久记忆。

版本 2 台账只依赖 JSON、本地资料快照和 SHA-256；项目路径相对台账所在目录，不依赖 agent 的启动目录。可移植性已经按这些接口设计；未在每个平台实际运行的行为不能写成已经验证。

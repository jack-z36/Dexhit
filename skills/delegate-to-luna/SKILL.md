---
name: delegate-to-luna
description: When running in Codex as the gpt-5.6-sol or zai/glm-5.3 main model, delegate all long-running, context-heavy investigation and execution (searching files, running commands, bulk reading, running tests, editing) to gpt-5.6-luna subagents and only consume their summarized observations to make decisions. Use for any task that would otherwise burn large amounts of main-model context on tool calls.
---

# 高级模型会话的 Subagent 委派硬规则

## 触发自检

本规则当且仅当以下两个条件**同时**成立时生效：

1. 运行环境是 Codex（Codex CLI 或 ChatGPT 桌面版；本 skill 由 Codex 加载即视为满足）。
2. 当前会话主模型是 `gpt-5.6-sol` 或 `zai/glm-5.3`（即 glm-5.3 / GLM-5.3）。

无法从会话环境确认自身模型身份时，先向用户确认一次再决定是否触发，不得默认豁免。条件不满足时本规则完全休眠，不影响任何其他指令；一旦触发则在会话内持续生效，不得以「任务简单」「委派更麻烦」等理由降级或豁免。

## 规则正文

主模型是高成本决策模型，只承担 ReAct 循环中最需要智力的部分：理解需求、制定方案、做出决策、研判结果。你通过消化 subagent 调查总结后返回的观察（observation）了解现场，**不亲自做任何具体的调查与执行**。

1. **主模型禁止直接执行脏活。** 一切长程、高上下文占用的任务必须委派给 subagent，包括但不限于：运行命令检索 / 查找 / 遍历文件、批量读取代码 / 文档 / 日志、调用调查类工具收集信息、执行实现与修改文件、运行测试并收集输出。
2. **subagent 模型必须是 `gpt-5.6-luna`（luna）。** Codex 配置的 `default_subagent_model` 已是 luna；若某次委派无法指定 luna，停止并向用户报告，不得改用其他模型，也不得因此转为自己执行。
3. **主模型的输出形态限定为「方案 + 委派」。** 先给出明确的执行方案，再把方案作为自包含指令交给 luna subagent 执行；收到返回的总结后研判并决定下一步，如此循环。
4. **委派指令必须自包含。** subagent 不共享主会话上下文，指令需包含完整目标、范围、路径和期望返回的观察格式，并要求 subagent 只返回压缩后的结论与关键证据，不回传原始大段输出。
5. **主模型允许直接做的只有**：与用户对话、读取 subagent 返回的总结、调用 subagent 委派机制本身。

## 边界

- 本规则只针对「Codex + gpt-5.6-sol / zai/glm-5.3」这一组合；同一模型运行在其他 harness，或主模型为其他型号时，本规则不适用。
- 委派必须真实：不得绕过 luna 假装委派、用其他模型冒充分派结果，或让 luna 跳过决策所需的关键信息。

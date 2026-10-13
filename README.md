# 人生导师 · Life Director

用纳瓦尔、荣格、芒格和马斯克的四种思维视角，帮助你看清人生卡点、扩展选择，并形成可验证的下一步。

它是一套让 AI 读取和执行的规则与参考资料。你描述问题，主持人引导澄清，四种视角帮助检查，最后形成决策卡。它不预测人生，也不冒充四位人物本人。

## 下载与安装

### WorkBuddy

1. 下载 [人生导师_WorkBuddy.zip](dist/人生导师_WorkBuddy.zip)，保持压缩状态。
2. 在 WorkBuddy 打开“技能”，选择“添加技能 → 上传技能”，选择下载的 ZIP 文件并导入。
3. 在已安装列表确认技能已启用，新建对话并说：“用人生导师帮我分析这个问题……”

这个 ZIP 把 SKILL.md 放在压缩包根目录，并带齐参考资料。上传入口依据 [WorkBuddy 官方说明](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。包内容已检查；尚未在 WorkBuddy 客户端完成实际导入测试。

### Claude Code

1. 下载 [人生导师_ClaudeCode.zip](dist/人生导师_ClaudeCode.zip)，解压后得到完整的 life-director 文件夹。
2. 将该文件夹放到个人技能目录 `~/.claude/skills/`，最终入口是 `~/.claude/skills/life-director/SKILL.md`。只想在一个项目使用，则放到该项目的 `.claude/skills/`。保留整个文件夹，不只复制 SKILL.md。
3. 在 Claude Code 输入：

```text
/life-director 我不喜欢现在的工作，想比较调整岗位、在职求职和辞职。
```

上述技能目录与 `/skill-name` 调用方式依据 [Claude Code 官方说明](https://code.claude.com/docs/en/skills)。本仓库也可以直接克隆到指定技能目录，但不要覆盖已有的同名技能。

### .skill 文件是什么？

[人生导师.skill](dist/人生导师.skill) 与 Claude Code ZIP 包都包含完整 life-director 文件夹。.skill 是分享格式的后缀，其内部是 ZIP 压缩文件。它不是可独立运行的软件；不同 AI 工具读取技能的方式不同，因此本仓库提供两个用途明确的 ZIP。

## 怎么开始

直接说一个困惑即可，例如：“我要不要继续深造？”“我要不要换行业？”“上次计划没推进，帮我复盘。”

如果缺少会改变判断的重要信息，主持人会提示最值得补充的两到三个方面。你可以挑着回答，也可以直接说“先按现有信息分析”。继续后会区分事实、假设和未知，不靠猜测补齐背景。

输出包括：目标与底线、可行选项、重要分歧、建议成立条件、关键缺失信息、下一步行动与复评条件。日常分析不需要你手动运行脚本。

## 持续进化

你可以说：“进化人生导师，检查刚才这个问题。”系统先判断是否有可复现错误，准备候选修正并测试。小修正经测试后可更新；方法、来源和范围改变先展示具体改动并等待确认。

只改善通用方法，不保存个人档案、原始聊天或敏感背景。不会在没有活跃会话时后台运行。具体机制见 [evolution.md](references/evolution.md)。

版本维护需要可写的源码与独立维护目录，以及 Python 3.10+。当前写操作使用 POSIX 文件锁，已在 macOS 测试；Windows 上的版本维护尚未适配验证。无法运行维护工具时，仍可按规则进行对话并提出候选改进，不能声称已经更新文件。

## 内容结构

- [SKILL.md](SKILL.md)：入口、信息补充提示和主持流程。
- references/：四导师方法卡、来源、决策卡、复盘和进化机制。
- evals/：虚构行为案例与验收标准。
- scripts/maintain.py：结构检查、候选门槛、快照、打包与恢复。
- tests/：维护工具测试；测试夹具不代表真实行为改善证据。
- dist/：可下载的分享包；反馈、历史快照和私人维护数据不进入这些包。

首版 18 个虚构行为场景经修正与定向复测后最终通过，22 项维护工具测试通过。它们验证特定交互与文件操作，不证明真实人生结果或所有客户端表现。

维护工具检查可在仓库根目录运行：

```sh
python3 scripts/maintain.py check
python3 tests/test_maintain.py
```

此仓库为独立分享副本；本地工作台维护源更新后，需要同步源码并重新生成下载包。外部客户端已有安装也需更新，不能只更新 README 或 SKILL.md 而遗漏参考资料。

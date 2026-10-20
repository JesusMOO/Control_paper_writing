# 长任务台账与检查

## 使用范围

泛控制类文章的整篇写作或跨会话任务在用户项目目录创建/更新 `paper-state.json`；先复用已有台账，不覆盖用户有效记录。复制 [模板](../assets/paper-state.json) 后填真实材料，空值表示尚未提供，不是已核验。局部润色、单段写作可只记录受影响证据，无须新建完整项目。

台账只记录决定、证据索引及用于核对的短片段，不复制全文或让模型推理记录代替原始材料。正文按用户格式保存。恢复时读 brief、decisions、open_issues 和当前章节，再打开相关真实文件。

## 数据约定

JSON 使用 UTF-8，`schema_version` 固定为 **2**。模板中的所有顶层字段保留；可增加项目自用字段，但脚本不会验证这些扩展字段。下面列出的必引作者、标准调整和正文定位是正式字段，不能省略。

| 字段 | 填写规则 |
| --- | --- |
| brief | object/scenario/problem/method/language 是字符串或 null；innovation_focus 为 object/scenario/method 之一，优先评估方法创新，不要求三个维度都创新。narrative_mode 为 scenario/method，由使用者选择场景论/方法论，与创新维度分别记录；尚未选择时为 null |
| journal | name/official_url/checked_at 是字符串或 null；只有打开并核对当前官方页面后 verified 才为 true，日期用 ISO 格式 |
| requirements | 默认 min_references=40、self_citations=[6,7]、min_proved_properties=1；调整必须有下述 requirement_overrides，不能为通过脚本降低目标 |
| requirement_overrides | 正式调整记录数组；未调整时为空。每项 field、from、to、reason、authorization，规则见下文 |
| required_authors | 必引作者数组；未指定时为空，每项 id、name、identity、identity_verified、min_citations，规则见下文 |
| manuscript | body_file/body_sha256 定位当前审查正文；abstract_sentences 为五句数组，conclusion_paragraphs 为两段数组；chapters 是完整六章，status 为 planned/draft/ready，artifacts 为本地文件定位数组；pages/reference_pages 来自实际排版，否则 null；format_verified 需要实际核验 |
| checks | 模板列出的七项人工核对，null 表示未核对；true/false 记录实际结果，不能从标题或脚本退出码推断 true |
| sources | 文献条目数组，字段见下文；数量只统计实际 cited 且 relevant 的不同来源 |
| evidence | 证据条目数组；每个 verified 记录都应有本地 locator、文件 sha256 和适用范围 scope |
| claims | 贡献及正文事实/理论/数字主张，关联证据 ID 和稿内位置 |
| results | 定量比较，关联具体 claim_id、实验 evidence_id、场景、口径与数值 |
| open_issues | 对象数组，每项 id、severity（blocking/major/minor）、detail；解决后删除该项或移入 decisions，并保留理由 |
| decisions | 字符串数组，记录用户已确认的选择、约束变更及原因；不要把待确认事项写成已经同意 |

ID 在所有 required_authors/sources/evidence/claims/results/open_issues 中全局唯一且稳定，例如 A1、S1、E1、C1、R1、I1。定位改动不重编号。证据改为 pending/invalid 时同步撤回依赖它的正文结论，不能只更新状态。

`brief.narrative_mode` 只登记本稿使用者已明确选择的叙述方式，在 `decisions` 保存实际答复依据；已有明确选择时接续复用。未答复时保留 null，不由 agent 默认填 scenario 或 method。旧版本 2 台账缺少此字段仍可读取，脚本将其列为待选择项，最终检查前须补齐真实选择；不能为通过检查代填。脚本仅核对字段，不验证对话真实性，agent 须核对实际答复。

每轮文献检索与引用整理结束后，在 `open_issues` 登记轮次、累计有效引用数、本轮检索范围、交付清单位置和待答复问题；待使用者检查项使用 blocking，不能把尚未收到的答复写入 `decisions`。使用者实际答复后，将决定、补充方向和答复依据记入 `decisions`，再移除相应待答复项。恢复任务时先核对本轮状态与真实答复，只有明确选择继续才进入下一轮；不能沿用上一轮的继续答复来启动更多轮次。

## 必引作者与标准调整

将用户指定的每位作者写入 `required_authors`：`id` 为稳定作者 ID，`name` 为姓名，`identity` 记录机构、ORCID、代表论文或其他身份依据，`identity_verified` 只有核对同名身份后才为 true；尚未核实时在 identity 中说明缺口。`min_citations` 是要求引用的不同成果篇数，未指定数量时为 1。

在对应 source 的 `author_ids` 中填匹配的必引作者 ID，并保留该论文完整的真实作者信息；此数组不是全体作者名单。脚本逐位统计相关且在审查正文出现引文标记的不同来源，不依赖手工添加 open_issues 才能发现漏引。未核对身份或数量不足会阻止最终检查通过。读取原论文核对身份、成果归属及论证联系仍由 agent 完成；不能删掉用户指定的作者来消除错误。

改变三项默认数量标准时，每个改变的字段保留一项当前有效 `requirement_overrides`：`field` 为要求名，`from` 为该字段的固定默认值，`to` 为当前 requirements 值，`reason` 说明原因，`authorization` 定位用户明确要求或已确认的调整依据，例如具体消息内容与日期。旧调整保留在 decisions；当前有效记录不能重复、与现值不符或缺少授权依据。脚本会拦截无记录的变更，但不能验证 authorization 中的文字是否真由用户授权；agent 必须回看实际对话或原始记录。仅出现期刊冲突或材料不足不能自动视为允许降低标准。

旧台账仍采用 30 篇基准时，先核对本次实际要求：使用当前默认规范的项目将 `min_references` 更新为 40；已有使用者明确调整的项目保留原始授权依据，并以当前默认值 40 重新登记有效调整。无法确认的要求保留为未决项，不补造授权，不把“停止检索”解释为降低篇数要求。

## 正文与文件版本

`manuscript.body_file` 指向当前稿件的 **UTF-8 Markdown、LaTeX 或纯文本审查正文**，包括摘要、六章及正文引用标记。正文沿用用户的原始格式；PDF/DOCX 可另导出用于核对的文本，脚本不负责转换。审查正文不包含独立书目列表，避免把仅列在书目中的引文标记计为正文引用。导出后人工确认未丢失数字、引用和公式所需信息。

`body_sha256`、source 的 `snapshot_sha256` 和 evidence 的 `sha256` 都是实际文件字节的 SHA-256 十六进制值，不填猜测值。文献可以使用已读取的本地全文、作者稿或摘录快照，注明阅读范围，不以网址代替快照。证据可为 PDF、图片、CSV、代码、证明文本等本地文件；脚本只校验文件与版本，不自动解析所有格式。

台账中的本地相对路径相对 **paper-state.json 所在目录**，与执行命令的当前目录无关；技能自身的参考、模板和脚本链接相对技能目录。`locator`、章节 artifacts 可以用 `文件路径#稿内定位`，但 `#` 后的位置由人工核对。摘要句和总结段按实际文字填入，脚本仅规范化空白后查找片段。主张 locations 仍需人工确认其章节与上下文。

计算文件校验值可使用 agent 的文件能力，或 Python 标准库：

```python
from hashlib import sha256
from pathlib import Path
checksum = sha256()
with Path("实际文件路径").open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        checksum.update(chunk)
print(checksum.hexdigest())
```

材料改动后重新读取并核对受影响主张、数值和引用，再更新校验值。仅重算校验值不能证明内容仍有效；无法复核时把有关记录改为 pending，撤回相应完成声明。

## 条目字段

下面是字段说明，不是虚构的可用证据。逐项从实际材料填入：

- **source：** `id`、`locator`（原始 DOI、网址或文件定位）、`year`（整数或 null）、`verification`（unverified/metadata/content）、`relevant`、`cited`（布尔）、`is_self`（布尔或 null）、`author_ids`（必引作者 ID 数组）、`citation_tokens`（实际正文引文标记数组）、`snapshot_file`、`snapshot_sha256`（字符串或 null）。引文标记应包含完整语法，例如 `[@S1]`、`\cite{key}` 或排版后的 `[12]`，不能用裸数字、作者姓名或书目条目代替；组合引用保存实际完整标记，人工确认来源对应关系。content 表示已核对用于论证的内容，metadata 仅核对书目信息。另保存题名、全体作者、DOI、阅读范围及支持的论证；检索时记录可核实的发表时作者单位、地区及未知项，供每轮引用检查。
- **evidence：** `id`、`kind`（literature/proof/experiment/derivation/implementation）、`status`（pending/verified/invalid）、`locator`、`sha256`、`scope`（字符串或 null）、`source_id`（文献证据指向 source ID，其他类型为 null）、`properties`（字符串数组，证明记录可使用 robustness/convergence/stability）。证明核验后才把性质加入此数组；verified 记录必须有可读文件及匹配校验值。
- **claim：** `id`、`text`、`kind`（novelty/literature/theory/quantitative/modeling/application）、`evidence_ids`（证据 ID 数组）、`locations`（稿内位置数组）、`innovation_dimension`（object/scenario/method 或 null）。novelty 必须与 brief.innovation_focus 一致，并有相关工作比较证据；其他类型可为 null。theory 指需要证明的性质主张；普通公式推导用 modeling 并关联 derivation。候选创新只关联未核验材料时仍属于待补。
- **result：** `id`、`claim_id`、`evidence_id`、`metric`、`unit`、`scenario`、`direction`（lower/higher）、`basis`（relative_percent/absolute/percentage_points）、`baseline`、`proposed`、`reported_value`（后三项为有限数字或 null）、`reported_text`（数字字面字符串或 null）、`mentions`（正文数字片段数组）。reported_value 是写出的改进值，不是原始指标；reported_text 保留稿件精度，例如 `"0.0002"` 或 `"2.0e-4"`，不带单位。空值只可保留在工作台账。

每个 result 的 `mentions` 记录该改进值在摘要、正文和总结中的全部重复表述，每项 `location` 为 abstract/body/conclusion，`quote` 为实际文字片段，`value_text` 为该片段中的数字字面。正文使用 `2\times10^{-4}`、`2\cdot10^{-4}` 等科学计数法时，填写等值且保持相同精度的 `2e-4` 或 `0.0002`；`2.00\times10^{-4}` 对应 `2.00e-4` 或 `0.000200`。摘要记录使用完整第五句，总结记录使用包含该数字的完整总结段；正文可用足够明确的句子或图表片段。各处允许合法的不同舍入精度，但必须复算一致。遗漏的片段不会被脚本自动发现，agent 仍须搜索所有重复数字。

比较口径：relative_percent 使用相对改进百分比，仅用于适合相对比较的非负指标且基线大于零；absolute 使用按指标方向计算的绝对改善；percentage_points 使用 **0–100 的百分比数值** 计算百分点差。例如 80 到 90 的 higher 比较：reported_value 为 10，而非 0.1。减退可得到负改善，如实记录。

## 运行只读检查

```bash
python3 /path/to/control-paper-writing/scripts/audit_state.py /path/to/project/paper-state.json
python3 /path/to/control-paper-writing/scripts/audit_state.py /path/to/project/paper-state.json --final --json
```

脚本不写台账、不联网、不执行台账中的路径或命令。证据文件分块计算 SHA-256，仅审查正文保留内容供文本核对；单次运行内复用文件版本未变的校验结果，每条记录仍分别核对其预期校验值。缓存不跨运行保留，读取过程中发生版本变化会报错。默认允许工作稿并将未完成项列为警告；无效 ID、伪称 verified 的空记录、已变化的文件、错误数字或无授权记录的标准变更会报错。`--final` 把完成缺口升级为错误，包括使用者的叙述方式选择、创新主线、必引作者、正文五句/两段/六章、文件版本、官方格式、人工检查、文献目标、性质证明和量化结果。

退出码：0 表示本次机械检查无错误（仍可能有警告）；1 表示证据断链、计算错误或完成条件不足；2 表示文件/JSON/字段类型或结构无效。报告值按其数字字面的末位精度采用半个末位单位的舍入容差，并仅加入按数值规模计算的浮点误差。例如 `33.33` 允许正常的两位小数舍入；微小绝对差 `0.0002` 不会使用统一的 0.05 容差。不能降低稿件精度掩盖实际错误。

把脚本输出称为“台账检查”，不要称为“论文审稿通过”。脚本读取正文核对已登记片段和引文标记，读取证据字节核对版本，但不验证定理、文献相关性、实验真实性、原始数据与 baseline/proposed 的对应、实际页面、句号数量、作者身份或授权真实性。引文标记出现不证明引用语境正确；来源去重可归并裸 DOI、`doi:` 与 `doi.org`/`dx.doi.org` 的常见写法，一般 URL 仅统一协议和主机名大小写，路径、查询及本地定位保留大小写，其他来源别名仍需人工归并。这些仍由 agent 读取材料核对。五个数组条目不保证真的五句，ready 不保证正文完成，SHA-256 匹配不证明科学真实性。

## 版本 1 台账迁移

脚本拒绝版本 1，并提示迁移说明，不自动覆盖用户记录。保留旧台账原件，在新文件中复制版本 2 模板，迁入旧版真实字段及稳定 ID，再完成以下补充：

1. 用 brief.innovation_focus 记录对象、场景或方法择一创新，删除旧 x_definition；为 novelty 主张填写匹配维度。另用 brief.narrative_mode 记录使用者选择的场景论或方法论，没有真实答复时保留 null 并提问。
2. 从实际用户要求填 required_authors；从真实已确认的调整填 requirement_overrides，不补造授权。
3. 定位当前正文、文献和证据快照，重新读取并核对，计算实际校验值；新增正文引文标记与必引作者关联。
4. 为结果填写 reported_text 与实际 mentions，复算摘要第五句及所有重复结果；资料不足保留 null、pending 或明确未决项。
5. 先运行普通检查处理断链和不一致，再按任务进度决定是否运行 --final；不继承未经重新核对的 true/verified。

模板应在普通模式得到待补警告，在 --final 得到未完成错误；不能为了干净日志预先填 true 或伪造记录。修改稿更新后仅复查受影响内容；提交最终稿前再执行整篇检查。

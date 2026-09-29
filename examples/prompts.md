# Prompt examples

These examples assume the tool is already connected and enabled.

## English

### Deep think, fixed effort

> Before your final answer, call `render_thinking_block`. Use `deep_think` style, `medium` effort, and the `microglow` skin. Work through the evidence, uncertainty, alternatives, and tradeoffs in the tool block, then answer normally.

### Let the model choose

> For non-trivial requests, call `render_thinking_block` before answering. Choose `style`, `effort`, and `skin` based on the task, then continue with the final answer.

### Relational

> Before replying, call `render_thinking_block` with `relational` style, `medium` effort, and the `botanical` skin. Use a natural, flowing first-person companion voice. Explore what my words bring to mind, what you feel in this moment, what you are worried about or holding back, and the choices or tradeoffs you are making. Prioritize emotional connection over abstract analysis, and do not write a third-person strategy memo. Then continue with your reply.

### Short block

> Call `render_thinking_block` before answering. Use `deep_think`, `low` effort, and the `microglow` skin. Keep the block below 120 words, then give a concise final answer.

## 中文

### Deep think，固定强度

> 在给出最终答案前，先调用 `render_thinking_block`。使用 `deep_think` 文体、`medium` 强度与 `microglow` 皮肤，在工具卡片里处理证据、不确定性、替代方案和取舍，然后正常回答。

### 让模型自己选择

> 遇到不简单的问题时，在回答前调用 `render_thinking_block`。根据任务自己选择 `style`、`effort` 和 `skin`，工具完成后继续给出正式答案。

### 关系陪伴

> 回复前先调用 `render_thinking_block`，使用 `relational` 文体、`medium` 强度与 `botanical` 皮肤。用第一人称、自然流动且连贯的语气，写我的话让你想到什么、此刻有什么感受、在担心或忍住什么，以及正在作出的选择或取舍。让情感连接优先于抽象分析，不要写成第三人称的回答策略报告。然后继续回复。

### 限制长度

> 回答前调用 `render_thinking_block`，使用 `deep_think`、`low` 和 `microglow` 皮肤。卡片内容控制在 200 个汉字以内，然后给出简洁答案。

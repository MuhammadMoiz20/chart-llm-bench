# Models to request on the proxy

Draft message for the proxy admin:

> Hi — the proxy works great, thanks. Two things:
>
> 1. `us.anthropic.claude-haiku-4-5-20251001-v1:0` and `us.anthropic.claude-opus-4-6-v1` are listed in `/v1/models` but return *"Model access is denied due to IAM user or service role is not authorized to perform the required AWS Marketplace actions"*. Sonnet 4.6 works fine. Haiku is the one I'd actually want (it's the closed model priced in the same league as the open ones).
> 2. Could you add these open-weight Bedrock models? All are cheap and relevant for the structured-output work I'm testing:
>    - `qwen.qwen3-235b-a22b-2507-v1:0`
>    - `qwen.qwen3-coder-30b-a3b-v1:0`
>    - `qwen.qwen3-coder-480b-a35b-v1:0`
>    - `deepseek.v3-v1:0` (DeepSeek V3.1)
>    - `openai.gpt-oss-20b-1:0`
>    - `meta.llama4-maverick-17b-instruct-v1:0` and `meta.llama4-scout-17b-instruct-v1:0`
>    - `mistral.mistral-large-2407-v1:0`
>    - Kimi K2 if it's available in the region (`moonshot.kimi-k2-*`)
>    - `amazon.nova-lite-v1:0` as a cheap closed baseline
>
> Spend so far is under $5 of the $100. Thanks!

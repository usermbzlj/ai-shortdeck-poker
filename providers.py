from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    base_url: str
    models: tuple[str, ...]
    thinking: bool


PROVIDERS = {
    '内置机器人': Provider('builtin://bot', ('紧凶', '松凶', '跟注站'), False),
    '真人（我来打）': Provider('builtin://human', ('真人',), False),
    'DeepSeek': Provider('https://api.deepseek.com/v1', ('deepseek-chat', 'deepseek-reasoner'), True),
    'OpenAI': Provider('https://api.openai.com/v1', ('gpt-4o', 'gpt-4o-mini', 'gpt-4.1'), False),
    '豆包/Doubao(火山方舟)': Provider('https://ark.cn-beijing.volces.com/api/v3', ('doubao-seed-1-6-250615', 'doubao-1-5-pro-32k-250115'), True),
    '智谱 GLM': Provider('https://open.bigmodel.cn/api/paas/v4', ('glm-4.5', 'glm-4-flash'), True),
    'Moonshot/Kimi': Provider('https://api.moonshot.cn/v1', ('moonshot-v1-8k', 'kimi-k2-0711-preview'), False),
    '通义千问 DashScope': Provider('https://dashscope.aliyuncs.com/compatible-mode/v1', ('qwen-plus', 'qwen-turbo', 'qwen-max'), False),
    'OpenRouter': Provider('https://openrouter.ai/api/v1', ('openai/gpt-4o-mini', 'deepseek/deepseek-chat'), False),
    '本地 Ollama': Provider('http://localhost:11434/v1', ('qwen3:8b', 'llama3.2'), False),
    '自定义': Provider('', (), True),
}


def infer_provider(base_url: str) -> str:
    base = base_url.rstrip('/')
    for name, preset in PROVIDERS.items():
        if preset.base_url and base in (preset.base_url, preset.base_url.removesuffix('/v1')):
            return name
    return '自定义'


def sends_thinking(mode: str, provider: str = '自定义') -> bool:
    return mode == 'send' or (mode != 'omit' and PROVIDERS.get(provider, PROVIDERS['自定义']).thinking)


PERSONAS = {
    '紧凶职业': '以职业选手的纪律挑选起手牌，入池后积极进攻，理性分析对手范围。',
    '疯狂松凶': '宽范围入池，频繁施压与诈唬，用进攻迫使对手犯错。',
    '话痨嘴炮': '决策时保持策略思考，发言幽默犀利，喜欢用嘴炮制造心理压力。',
    '冷血数学家': '用底池赔率、胜率和期望值做决定，不受情绪影响。',
    '保守岩石': '严格挑选强牌，谨慎控制风险，不轻易追逐边缘听牌。',
}

import asyncio
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("./tokenizer", trust_remote_code=True)


async def async_encode(text):
    return await asyncio.to_thread(tokenizer.encode, text)


async def get_token_count(text: str) -> int:
    tokens = await async_encode(text)
    return len(tokens)


async def get_messages_token_count(messages: list[dict[str, str]]) -> int:
    token_count = 0
    for message in messages:
        token_count += await get_token_count(message["content"])
    return token_count

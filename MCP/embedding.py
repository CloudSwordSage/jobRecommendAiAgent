# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 14:21:01
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : embedding.py
# @License : Apache-2.0
# @Desc    : 嵌入模型类

import asyncio
from typing import List
from langchain.embeddings.base import Embeddings
from openai import AsyncOpenAI


class AsyncOpenAIEmbeddings(Embeddings):
    def __init__(self, base_url: str, api_key: str, model_name: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model_name = model_name

    async def _get_embedding(self, text: str) -> List[float]:
        response = await self.client.embeddings.create(
            input=text, model=self.model_name
        )
        return response.data[0].embedding

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.gather(*[self._get_embedding(text) for text in texts])

    async def aembed_query(self, text: str) -> List[float]:
        return await self._get_embedding(text)

    async def test_api(self) -> bool:
        try:
            await self.client.embeddings.create(input="test", model=self.model_name)
            return True
        except Exception:
            return False

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return asyncio.run(self.aembed_documents(texts))

    def embed_query(self, text: str) -> List[float]:
        return asyncio.run(self.aembed_query(text))

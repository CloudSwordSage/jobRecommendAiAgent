# -*- coding: utf-8 -*-
# @Time    : 2025/11/25 15:35:40
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : vector_service.py
# @License : Apache-2.0
# @Desc    : 向量存储及匹配服务

from __future__ import annotations
import os
import asyncio
from typing import List, Dict, Optional, Tuple
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from config.config import Config
from model.job import Job
from utils.database import AsyncSessionLocal
from .embedding import AsyncOpenAIEmbeddings


class JobVectorService:
    def __init__(self, index_dir: str, api_base: str, api_key: str, model_name: str):
        self.index_dir = index_dir
        self.embedding = AsyncOpenAIEmbeddings(
            base_url=api_base, api_key=api_key, model_name=model_name
        )
        self.store: Optional[FAISS] = None
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100000)
        self._worker_task: Optional[asyncio.Task] = None
        self._batch_size: int = 64
        os.makedirs(self.index_dir, exist_ok=True)
        self._load_or_init()
        self._register_event()

    def _load_or_init(self) -> None:
        try:
            self.store = FAISS.load_local(
                self.index_dir, self.embedding, allow_dangerous_deserialization=True
            )
        except Exception:
            self.store = None

    def _make_document(self, job: Job) -> Document:
        content_parts: List[str] = []
        if job.job_title:
            content_parts.append(job.job_title)
        if job.job_description_requirements:
            content_parts.append(job.job_description_requirements)
        if job.skill_requirements:
            content_parts.append(job.skill_requirements)
        content = "\n".join([p for p in content_parts if p]).strip()
        return Document(page_content=content, metadata={"jid": job.jid})

    def _add_docs_sync(self, docs: List[Document]) -> None:
        if self.store is None:
            self.store = FAISS.from_documents(docs, self.embedding)
        else:
            self.store.add_documents(docs)
        self._shrink_docstore()
        self.store.save_local(self.index_dir)

    def _shrink_docstore(self) -> None:
        if not self.store or not getattr(self.store, "docstore", None):
            return
        d = self.store.docstore._dict
        for k, v in list(d.items()):
            jid = v.metadata.get("jid") if getattr(v, "metadata", None) else None
            d[k] = Document(page_content="", metadata={"jid": jid})

    async def _worker(self) -> None:
        batch: List[Job] = []
        while True:
            job = await self._queue.get()
            batch.append(job)
            try:
                while len(batch) < self._batch_size:
                    try:
                        next_job = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    else:
                        batch.append(next_job)
                await self._upsert_jobs_batch(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()
                batch.clear()

    async def enqueue_job(self, job: Job) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
        await self._queue.put(job)

    async def _upsert_jobs_batch(self, jobs: List[Job]) -> None:
        async with self._lock:
            docs = [self._make_document(j) for j in jobs]
            await asyncio.to_thread(self._add_docs_sync, docs)

    async def upsert_job(self, job: Job) -> None:
        await self._upsert_jobs_batch([job])

    async def search_ids_async(self, query: str, topn: int) -> List[Tuple[int, float]]:
        if not self.store:
            return []
        # print(f"search_ids_async: query={query}, topn={topn}")
        vec = await self.embedding.aembed_query(query)
        # print(f"search_ids_async: vec length={len(vec)}")
        k_fetch = max(topn * 3, topn + 10)
        results = self.store.similarity_search_with_score_by_vector(vec, k=k_fetch)
        # print(f"search_ids_async: results length={len(results)}")
        seen: set[int] = set()
        out: List[Tuple[int, float]] = []
        for doc, score in results:
            jid = doc.metadata.get("jid") if doc.metadata else None
            # print(f"search_ids_async: jid={jid}, score={score}")
            if isinstance(jid, int) and jid not in seen:
                seen.add(jid)
                out.append((jid, float(score)))
                if len(out) >= topn:
                    break
        # print(f"search_ids_async: out length={len(out)}")
        return out

    async def search_async(self, query: str, topn: int) -> List[Dict]:
        pairs = await self.search_ids_async(query, topn)
        if not pairs:
            return []
        jids = [jid for jid, _ in pairs]
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Job).where(Job.jid.in_(jids)))
            jobs: List[Job] = result.scalars().all()
        job_map: Dict[int, Job] = {j.jid: j for j in jobs}
        out: List[Dict] = []
        for jid, score in pairs:
            if j := job_map.get(jid):
                out.append(
                    {
                        "jid": j.jid,
                        "score": score,
                        "job_title": j.job_title,
                        "job_description_requirements": j.job_description_requirements,
                        "company_name": j.company_name,
                        "salary": j.salary,
                        "location": j.location,
                        "edu_requirement": j.edu_requirement,
                        "exp_requirement": j.exp_requirement,
                        "company_type": j.company_type,
                        "company_industry": j.company_industry,
                    }
                )
        return out

    async def initial_sync(self) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Job))
            jobs: List[Job] = result.scalars().all()
        if not jobs:
            return
        existing_jids: set[int] = set()
        if self.store and getattr(self.store, "docstore", None):
            try:
                for _, d in self.store.docstore._dict.items():
                    jid = d.metadata.get("jid")
                    if isinstance(jid, int):
                        existing_jids.add(jid)
            except Exception:
                existing_jids = set()
        new_jobs = [j for j in jobs if j.jid not in existing_jids]
        if not new_jobs:
            return
        async with self._lock:
            docs = [self._make_document(j) for j in new_jobs]
            await asyncio.to_thread(self._add_docs_sync, docs)

    def _register_event(self) -> None:
        def _after_insert(mapper, connection, target):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.enqueue_job(target))
            except RuntimeError:
                asyncio.run(self.upsert_job(target))

        event.listen(Job, "after_insert", _after_insert)


job_vector_service: Optional[JobVectorService] = None


def init_job_vector_service() -> None:
    index_dir = Config.faiss_index_dir
    api_base = Config.embedding_api_base_url
    api_key = Config.embedding_api_key
    model_name = Config.embedding_model_name
    if not api_base or not model_name:
        return
    global job_vector_service
    job_vector_service = JobVectorService(
        index_dir=index_dir,
        api_base=api_base,
        api_key=api_key or "none",
        model_name=model_name,
    )
    print(
        f"job_vector_service initialized: index_dir={index_dir}, api_base={api_base}, model_name={model_name}"
    )
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(job_vector_service.initial_sync())
    except RuntimeError:
        asyncio.run(job_vector_service.initial_sync())

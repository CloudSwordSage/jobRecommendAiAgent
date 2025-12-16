# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:34:47
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : job.py
# @License : Apache-2.0
# @Desc    : 岗位模型

from sqlalchemy import Column, Integer, String, Boolean, Enum, select, ForeignKey, Text
from sqlalchemy.sql import expression
from sqlalchemy.ext.asyncio import AsyncSession
from .base import Base


class Job(Base):
    __tablename__ = "job"

    jid = Column(
        Integer, primary_key=True, index=True, autoincrement=True, nullable=False
    )
    job_title = Column(String(255), nullable=True)  # 岗位标题
    job_description_requirements = Column(Text, nullable=True)  # 岗位描述和要求
    skill_requirements = Column(Text, nullable=True)  # 技能要求
    salary = Column(String(255), nullable=True)  # 薪资
    location = Column(String(255), nullable=True)  # 工作地点
    edu_requirement = Column(String(255), nullable=True)  # 学历要求
    exp_requirement = Column(String(255), nullable=True)  # 经验要求
    company_name = Column(String(255), nullable=True)  # 公司名称
    company_type = Column(String(255), nullable=True)  # 公司类型
    company_industry = Column(String(255), nullable=True)  # 公司行业

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        *,
        job_title: str | None = None,
        job_description_requirements: str | None = None,
        skill_requirements: str | None = None,
        salary: str | None = None,
        location: str | None = None,
        edu_requirement: str | None = None,
        exp_requirement: str | None = None,
        company_name: str | None = None,
        company_type: str | None = None,
        company_industry: str | None = None,
    ) -> "Job":
        job = cls(
            job_title=job_title,
            job_description_requirements=job_description_requirements,
            skill_requirements=skill_requirements,
            salary=salary,
            location=location,
            edu_requirement=edu_requirement,
            exp_requirement=exp_requirement,
            company_name=company_name,
            company_type=company_type,
            company_industry=company_industry,
        )
        db.add(job)
        await db.flush()
        await db.commit()
        await db.refresh(job)
        return job

# -*- coding: utf-8 -*-
# @Time    : 2025/12/15 10:15:04
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : job.py
# @License : Apache-2.0
# @Desc    :

import asyncio
import csv
import os


from model.job import Job
from utils.database import AsyncSessionLocal

_import_running = False


async def import_jobs():
    global _import_running
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        csv_path = os.path.join(base_dir, "data", "job_pre.csv")
        async with AsyncSessionLocal() as db:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                fast_jobs = []
                for index, row in enumerate(reader, start=1):
                    job = Job(
                        job_title=row.get("name") or None,
                        job_description_requirements=row.get("JDAndRequirements")
                        or None,
                        salary=row.get("Salary") or None,
                        location=row.get("Location") or None,
                        edu_requirement=row.get("EduRequirement") or None,
                        exp_requirement=row.get("ExpRequirement") or None,
                        company_name=row.get("CompanyName") or None,
                        company_type=row.get("CompanyType") or None,
                        company_industry=row.get("CompanyIndustry") or None,
                    )
                    db.add(job)
                    await db.commit()
                    # await asyncio.sleep(5)
    finally:
        _import_running = False
        print("Jobs imported")


async def start_import_jobs():
    global _import_running
    if _import_running:
        return {"status": "running"}
    _import_running = True
    asyncio.create_task(import_jobs())

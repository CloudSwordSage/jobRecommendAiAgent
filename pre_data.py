# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 15:29:08
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : pre_data.py
# @License : Apache-2.0
# @Desc    : 数据预处理

import ast
import contextlib
import re
import pandas as pd
from utils.normalize_salary import normalize_salary

from tqdm import tqdm

job_df = pd.read_csv("./data/job.csv")
col_names = [
    "岗位名称",
    "公司名称",
    "工作地点",
    "薪资",
    "时间",
    "其他介绍",
    "公司类型",
    "公司规模",
    "公司行业",
    "其他信息",
]
job2_df = pd.read_csv("./data/数据分析.csv", header=None, encoding="gbk")
if len(job2_df.columns) != len(col_names) or not set(col_names).issubset(
    set(job2_df.columns)
):
    job2_df.columns = col_names


def clean_text(value):
    if isinstance(value, (list, tuple)):
        return " ".join([str(i).replace("\xa0", " ").strip() for i in value])
    return "" if pd.isna(value) else str(value).replace("\xa0", " ").strip()


def clean_list(value):
    with contextlib.suppress(Exception):
        value = ast.literal_eval(value)
    if isinstance(value, (list, tuple)):
        return [str(i).replace("\xa0", " ").strip() for i in value]
    return "" if pd.isna(value) else value


resu = [
    [
        "name",
        "JDAndRequirements",
        "Salary",
        "Location",
        "EduRequirement",
        "ExpRequirement",
        "CompanyName",
        "CompanyType",
        "CompanyIndustry",
    ]
]

v = set()

for row in tqdm(job_df.iterrows(), total=len(job_df), desc="Processing rows"):
    row = row[1]
    item = [
        row["岗位名称"],
        row["岗位需求"],
        normalize_salary(row["薪资"]),
        row["工作地点"],
        row["学历要求"],
        row["工作经验"],
        row["企业"],
        row["公司类型"],
        "",
    ]
    key = tuple(item)
    if key in v:
        continue
    v.add(key)
    resu.append(item)

EDU_PATTERN = re.compile(
    r"(?:学历不限|不限学历|"
    r"(?:统招)?(?:博士|硕士|研究生|本科|学士|大专|专科|中专|高中|MBA|EMBA)(?:及以上|以上|或以上|起|优先)?|"
    r"(?:博士|硕士|研究生|本科|学士|大专|专科)(?:[\\/、或及]|与)?(?:博士|硕士|研究生|本科|学士|大专|专科)?(?:及以上|以上)?(?:学历)?|"
    r"(?:211|985|双一流|一本|二本)(?:院校)?)"
)

for row in tqdm(job2_df.iterrows(), total=len(job2_df), desc="Processing rows"):
    row = row[1]
    info_text = clean_list(row["其他介绍"])
    other_data_text = clean_list(row["其他信息"])
    location = row["工作地点"]
    exp = ""
    edu = ""
    for i in info_text:
        if "经验" in i or "在校" in i or "应届" in i:
            exp = clean_text(i).replace("经验", "")
        if EDU_PATTERN.match(i):
            edu = clean_text(i)

    jd = ";".join(other_data_text)
    company_type = clean_list(row["公司类型"])
    company_type = company_type[0] if company_type else ""
    industry_val = row["公司行业"]
    company_industry = clean_list(industry_val)
    company_industry = company_industry[0] if company_industry else ""
    item = [
        row["岗位名称"],
        jd,
        normalize_salary(row["薪资"]),
        row["工作地点"],
        edu,
        exp,
        row["公司名称"],
        company_type,
        company_industry,
    ]
    key = tuple(item)
    if key in v:
        continue
    v.add(key)
    resu.append(item)


res_df = pd.DataFrame(resu[1:], columns=resu[0])
res_df["EduRequirement"] = res_df["EduRequirement"].fillna("学历不限")
res_df["ExpRequirement"] = res_df["ExpRequirement"].fillna("经验不限")
res_df.to_csv("./data/job_pre.csv", index=False, encoding="utf-8-sig")

"""One module per source. Every module exposes:

    fetch(entry: dict) -> list[Job]      # list/board data (cheap)
    enrich(job: Job) -> Job              # optional: fetch full description for pre-filtered jobs

`entry` is the companies.yaml record (name, ats, id, bucket, industry, ...),
or the aggregator config block for aggregator sources.
"""
import importlib

ATS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio", "teamtailor", "workday", "browser"]
AGGREGATORS = ["adzuna", "jooble", "arbeitnow", "remotive", "ictjob", "stepstone"]


def get(name: str):
    if name not in ATS + AGGREGATORS:
        raise KeyError(f"unknown source type: {name}")
    return importlib.import_module(f"fetchers.{name}")

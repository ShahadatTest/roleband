"""Skills: closed catalogue + evidence-grounded per-job requirement extraction.

Modules:
- catalog:  load/validate catalog.yaml -> Catalog (concepts, guarded aliases)
- segment:  posting sections -> classified evidence units with stable offsets
- extract:  deterministic extraction -> job_skills / job_skill_evidence /
            job_qualifications (atomic per-job replacement)
- sync:     project the catalogue into skill_concepts / skill_aliases
"""

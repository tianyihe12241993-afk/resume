"""End-to-end check of job discovery on the tailor_studio system.

Signup -> create profile -> upload base resume -> search-config -> discover ->
approve top job -> tailor (real docx). Run:
  .venv\\Scripts\\python.exe scripts\\e2e_studio.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from tailor_studio import scheduler, storage
from tailor_studio.db import SessionLocal, Batch, JobUrl, Profile
from tailor_studio.main import app

BASE_DOCX = os.path.join(os.path.dirname(__file__), "..", "data", "base_resumes", "1.docx")
EMAIL = "e2e-discovery@example.com"
PW = "test-passw0rd!"


def main():
    with TestClient(app) as c:
        # 1. Auth (signup, or login if the user already exists)
        r = c.post("/api/signup", json={"email": EMAIL, "password": PW})
        if r.status_code == 409:
            r = c.post("/api/login", json={"email": EMAIL, "password": PW})
        assert r.status_code == 200, r.text
        print("1. auth OK:", r.json().get("email"))

        # 2. Create a profile + upload base resume
        r = c.post("/api/admin/profiles", json={"name": "E2E Discovery"})
        assert r.status_code == 200, r.text
        pid = r.json()["id"] if "id" in r.json() else r.json()["profile"]["id"]
        with open(BASE_DOCX, "rb") as fh:
            r = c.post(
                f"/api/admin/profiles/{pid}/resume",
                files={"file": ("base.docx", fh,
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        assert r.status_code == 200, r.text
        print(f"2. profile #{pid} created + base resume uploaded")

        pre_batches = {b.id for b in _batches(pid)}

        # 3. Search config (enable daily -> scheduler should register)
        cfg = {
            "keywords": "backend engineer", "locations": "Remote", "sites": "indeed",
            "remote": True, "hours_old": 336, "results_limit": 5, "ats_companies": "",
            "preferences": "prefer backend / platform infra roles",
            "min_score": 70, "schedule_hour": 9, "enabled": True,
        }
        r = c.post(f"/api/admin/profiles/{pid}/search-config", json=cfg)
        assert r.status_code == 200, r.text
        jobs = [j.id for j in scheduler._scheduler.get_jobs()] if scheduler._scheduler else []
        assert f"discovery-{pid}" in jobs, f"scheduler jobs={jobs}"
        print("3. search-config saved; scheduler registered:", jobs)

        # 4. Discover (background)
        r = c.post(f"/api/admin/profiles/{pid}/discover")
        assert r.status_code == 200, r.text
        print("4. discover:", r.json())

        # 5. Wait for the discovery batch
        new_bid = None
        for _ in range(60):
            for b in _batches(pid):
                if b.id in pre_batches:
                    continue
                db = SessionLocal()
                n = db.query(JobUrl).filter_by(batch_id=b.id, status="discovered").count()
                db.close()
                if n:
                    new_bid = b.id
                    break
            if new_bid:
                break
            time.sleep(2)
        assert new_bid, "no discovered batch produced in time"

        r = c.get(f"/api/admin/batches/{new_bid}")
        djobs = [j for j in r.json()["jobs"] if j["status"] == "discovered"]
        print(f"5. discovered batch #{new_bid}: {len(djobs)} jobs")
        for j in djobs[:5]:
            print(f"     score={j['score']} src={j['source']} | {str(j['title'])[:34]} | {str(j['score_reason'])[:32]}")
        assert all("score" in j and "source" in j and "score_reason" in j for j in djobs)

        # 6. Approve top-scored job -> tailor it
        top = max(djobs, key=lambda j: (j["score"] if j["score"] is not None else -1))
        r = c.post(f"/api/admin/batches/{new_bid}/approve", json={"job_ids": [top["id"]]})
        assert r.status_code == 200, r.text
        print(f"6. approve #{top['id']} (score {top['score']}):", r.json())

        # 7. Wait for tailoring (full constrained-rewrite pipeline)
        done = False
        for _ in range(90):
            r = c.get(f"/api/admin/batches/{new_bid}")
            j = next(x for x in r.json()["jobs"] if x["id"] == top["id"])
            if j["status"] == "done" and j["has_docx"]:
                done = True
                break
            if j["status"] in ("error", "needs_manual_jd"):
                print("   tailoring ended at:", j["status"], j.get("error_message"))
                break
            time.sleep(2)
        path = storage.generated_docx_path(new_bid, top["id"])
        print(f"7. tailored docx exists: {path.exists()} ({path.name if path.exists() else '-'}, "
              f"{path.stat().st_size if path.exists() else 0} bytes)")
        assert done and path.exists(), "approved job did not produce a tailored docx"

        # 8. Final status counts
        r = c.get(f"/api/admin/batches/{new_bid}")
        counts = {}
        for x in r.json()["jobs"]:
            counts[x["status"]] = counts.get(x["status"], 0) + 1
        print("8. final batch statuses:", counts)

    print("\nALL CHECKS PASSED")


def _batches(pid):
    db = SessionLocal()
    try:
        return db.query(Batch).filter_by(profile_id=pid).all()
    finally:
        db.close()


if __name__ == "__main__":
    main()

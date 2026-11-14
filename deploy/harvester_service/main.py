"""Cloud Run service wrapping tools/harvest_portal_dataset.py.

Exposes:
  POST /harvest  -> {job_id} (202)
  GET  /harvest/{job_id} -> {status, log_tail, result}
  GET  /healthz

Auth: X-API-Key header must match the HARVESTER_API_KEY env/secret.
"""

# v2 - PY artifact removed
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(os.environ.get("OIC_PROJECT_ROOT", "/app"))
HARVESTER = PROJECT_ROOT / "tools" / "harvest_portal_dataset.py"
CONFIG = PROJECT_ROOT / "config" / "harvester_config.json"

API_KEY = os.environ.get("HARVESTER_API_KEY", "")

app = FastAPI(title="OIC Harvester Console", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("OIC_CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict[str, Any]] = {}
LOCK = threading.Lock()


class HarvestRequest(BaseModel):
    url: str
    key: Optional[str] = None
    theme: Optional[str] = None
    scale: Optional[str] = None
    jurisdiction: Optional[str] = None
    dry_run: bool = True  # v1: dry-run only by default
    skip_wherobots: bool = True
    refresh_geolibre: bool = False


def _check_key(x_api_key: Optional[str]) -> None:
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _tail(path: Path, n: int = 80) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-n:])


def _run_job(job_id: str, req: HarvestRequest) -> None:
    JOBS[job_id]["status"] = "running"
    log_path = Path(JOBS[job_id]["log_path"])
    args = [
        "python",
        str(HARVESTER),
        "--config",
        str(CONFIG),
        "--url",
        req.url,
    ]
    if req.key:
        args += ["--key", req.key]
    if req.theme:
        args += ["--theme", req.theme]
    if req.scale:
        args += ["--scale", req.scale]
    if req.jurisdiction:
        args += ["--jurisdiction", req.jurisdiction]
    if req.dry_run:
        args += ["--dry-run"]
    if req.skip_wherobots:
        args += ["--skip-wherobots"]
    if req.refresh_geolibre:
        # live harvest only; ignored in dry-run
        pass

    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            proc = subprocess.run(
                args,
                cwd=str(PROJECT_ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=int(os.environ.get("OIC_JOB_TIMEOUT_SEC", "540")),
            )
        JOBS[job_id]["returncode"] = proc.returncode
        if proc.returncode == 0:
            JOBS[job_id]["status"] = "succeeded"
            # Optional GeoLibre refresh (only meaningful for live runs)
            if (not req.dry_run) and req.refresh_geolibre:
                refresh = PROJECT_ROOT / "tools" / "refresh_geolibre_library.py"
                if refresh.exists():
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write("\n[GEOLIBRE] refreshing library...\n")
                        subprocess.run(
                            ["python", str(refresh)],
                            cwd=str(PROJECT_ROOT),
                            stdout=lf,
                            stderr=subprocess.STDOUT,
                            text=True,
                            timeout=300,
                        )
        else:
            JOBS[job_id]["status"] = "failed"
    except subprocess.TimeoutExpired:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = "timeout"
    except Exception as exc:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc)
    finally:
        JOBS[job_id]["finished_at"] = time.time()


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/harvest", status_code=202)
def harvest(req: HarvestRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, str]:
    _check_key(x_api_key)
    if not req.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    with LOCK:
        # refuse if a job is still running
        if any(j.get("status") == "running" for j in JOBS.values()):
            raise HTTPException(status_code=409, detail="Another harvest is running; try again later")
        job_id = uuid.uuid4().hex[:12]
        log_path = Path("/tmp") / f"oic_harvest_{job_id}.log"
        JOBS[job_id] = {
            "status": "queued",
            "log_path": str(log_path),
            "started_at": time.time(),
            "request": req.model_dump(),
        }
        threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/harvest/{job_id}")
def harvest_status(job_id: str, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_key(x_api_key)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return {
        "job_id": job_id,
        "status": job["status"],
        "returncode": job.get("returncode"),
        "error": job.get("error"),
        "log_tail": _tail(Path(job["log_path"])),
        "started_at": job["started_at"],
        "finished_at": job.get("finished_at"),
    }

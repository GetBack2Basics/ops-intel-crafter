"""Initialize, commit, and push repository to https://github.com/GetBack2Basics/ops-intel-crafter.git."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.graphify_analysis import scan_repository  # noqa: E402

GIT_EXE = r"C:\Users\corea\AppData\Local\hermes\git\cmd\git.exe"
REMOTE_URL = "https://github.com/GetBack2Basics/ops-intel-crafter.git"


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    cmd = [GIT_EXE] + args
    print(f"[GIT] {' '.join(args)}")
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if res.stdout.strip():
        print(res.stdout.strip())
    if res.stderr.strip():
        print(res.stderr.strip())
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed with exit code {res.returncode}")
    return res


def main() -> None:
    report = scan_repository()
    if report["secret_leaks_detected"] > 0 or report["mock_violations_detected"] > 0:
        raise RuntimeError(f"Graphify gate blocked commit: {report}")
    print(
        f"[GRAPHIFY] Scanned {report['files_scanned']} modules | "
        f"Secrets={report['secret_leaks_detected']} | MockViolations={report['mock_violations_detected']}"
    )

    if not (ROOT / ".git").exists():
        run_git(["init"])

    run_git(["branch", "-M", "main"])

    remotes = run_git(["remote"], check=False).stdout.split()
    if "origin" not in remotes:
        run_git(["remote", "add", "origin", REMOTE_URL])
    else:
        run_git(["remote", "set-url", "origin", REMOTE_URL])

    run_git(["add", "."])

    status = run_git(["status", "--short"]).stdout.strip()
    if status:
        run_git(
            [
                "commit",
                "-m",
                "Implement Emergency Spatial Workbench, 3-level QA, NExT pop methods A/B/C, and plain-text query options",
            ]
        )

    # Fetch and merge any initial commit on remote main (e.g., initial GitHub README/LICENSE) preferring our working tree
    run_git(["fetch", "origin", "main"], check=False)
    run_git(
        ["merge", "origin/main", "--allow-unrelated-histories", "-X", "ours", "-m", "Merge remote-tracking branch 'origin/main'"],
        check=False,
    )

    run_git(["push", "-u", "origin", "main"])
    print(f"[GIT] Successfully pushed to {REMOTE_URL}")


if __name__ == "__main__":
    main()

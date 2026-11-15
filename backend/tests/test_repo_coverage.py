from __future__ import annotations

from app.repo_providers import compute_coverage, referenced_files


def test_referenced_files_exact_match_only():
    repo = {"src/app/actions.ts", "src/lib/supabase.ts", "README.md", "app/main.py"}
    docs = [
        "The data layer lives in `src/app/actions.ts` and the client in src/lib/supabase.ts.",
        "See ./README.md for setup. Also mentions main.py (bare, no dir) and http://x/y.ts (url).",
    ]
    refs = referenced_files(docs, repo)
    assert refs == {"src/app/actions.ts", "src/lib/supabase.ts", "README.md"}
    assert "app/main.py" not in refs  # bare 'main.py' must not match a full path
    assert all("://" not in r for r in refs)


def test_compute_coverage_by_dir_ranks_least_covered_first():
    files = [
        "src/app/page.tsx", "src/app/actions.ts",
        "src/components/A.tsx", "src/components/B.tsx", "src/components/C.tsx",
        "README.md",
    ]
    referenced = {"src/app/actions.ts", "README.md"}
    cov = compute_coverage(files, referenced)

    assert cov["fileCount"] == 6
    assert cov["documentedCount"] == 2
    by_dir = {d["dir"]: d for d in cov["byDir"]}
    assert by_dir["src"]["total"] == 5 and by_dir["src"]["documented"] == 1
    assert by_dir["(root)"]["total"] == 1 and by_dir["(root)"]["documented"] == 1
    # least-covered (src: 1/5 = .2) sorts before fully-covered ((root): 1/1)
    assert cov["byDir"][0]["dir"] == "src"
    # undocumented sample excludes the cited files
    assert "src/app/actions.ts" not in cov["undocumentedSample"]
    assert "src/components/A.tsx" in cov["undocumentedSample"]

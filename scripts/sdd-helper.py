import sys
import os
import re
import subprocess
from pathlib import Path

def get_git_dir():
    try:
        res = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, encoding="utf-8", check=True)
        return Path(res.stdout.strip())
    except Exception as e:
        print(f"Error getting git dir: {e}", file=sys.stderr)
        sys.exit(1)

def get_git_rev(rev):
    try:
        res = subprocess.run(["git", "rev-parse", rev], capture_output=True, encoding="utf-8", check=True)
        return res.stdout.strip()
    except Exception as e:
        print(f"Error getting git revision for {rev}: {e}", file=sys.stderr)
        sys.exit(1)

def get_git_short_rev(rev):
    try:
        res = subprocess.run(["git", "rev-parse", "--short", rev], capture_output=True, encoding="utf-8", check=True)
        return res.stdout.strip()
    except Exception as e:
        print(f"Error getting git short revision for {rev}: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_task_brief(plan_file, task_number, outfile=None):
    plan_path = Path(plan_file)
    if not plan_path.is_file():
        print(f"Error: plan file not found: {plan_file}", file=sys.stderr)
        sys.exit(2)
        
    if not outfile:
        git_dir = get_git_dir()
        sdd_dir = git_dir / "sdd"
        sdd_dir.mkdir(parents=True, exist_ok=True)
        outfile = str(sdd_dir / f"task-{task_number}-brief.md")
        
    content = plan_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    in_fence = False
    in_task = False
    task_lines = []
    
    # Matches headers like "### Task 1: " or "### Task 1"
    task_header_pattern = re.compile(rf"^#+\s+Task\s+{task_number}(?:\D|$)")
    other_task_header_pattern = re.compile(r"^#+\s+Task\s+\d+(?:\D|$)")
    
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            
        if not in_fence:
            if task_header_pattern.match(line):
                in_task = True
            elif other_task_header_pattern.match(line) and in_task:
                in_task = False
                
        if in_task:
            task_lines.append(line)
            
    if not task_lines:
        print(f"Error: task {task_number} not found in {plan_file}", file=sys.stderr)
        sys.exit(3)
        
    Path(outfile).write_text("\n".join(task_lines) + "\n", encoding="utf-8")
    print(f"wrote {outfile}: {len(task_lines)} lines")

def cmd_review_package(base, head, outfile=None):
    # Verify revisions
    base_rev = get_git_rev(base)
    head_rev = get_git_rev(head)
    base_short = get_git_short_rev(base)
    head_short = get_git_short_rev(head)
    
    if not outfile:
        git_dir = get_git_dir()
        sdd_dir = git_dir / "sdd"
        sdd_dir.mkdir(parents=True, exist_ok=True)
        outfile = str(sdd_dir / f"review-{base_short}..{head_short}.diff")
        
    # Get git log
    log_res = subprocess.run(["git", "log", "--oneline", f"{base}..{head}"], capture_output=True, encoding="utf-8", check=True)
    # Get git diff --stat
    stat_res = subprocess.run(["git", "diff", "--stat", f"{base}..{head}"], capture_output=True, encoding="utf-8", check=True)
    # Get git diff -U10
    diff_res = subprocess.run(["git", "diff", "-U10", f"{base}..{head}"], capture_output=True, encoding="utf-8", check=True)
    
    # Get count of commits
    count_res = subprocess.run(["git", "rev-list", "--count", f"{base}..{head}"], capture_output=True, encoding="utf-8", check=True)
    commit_count = count_res.stdout.strip()
    
    package_content = f"""# Review package: {base}..{head}

## Commits
{log_res.stdout}

## Files changed
{stat_res.stdout}

## Diff
{diff_res.stdout}
"""
    
    Path(outfile).write_text(package_content, encoding="utf-8")
    file_size = Path(outfile).stat().st_size
    print(f"wrote {outfile}: {commit_count} commit(s), {file_size} bytes")

def main():
    if len(sys.argv) < 2:
        print("Usage: python sdd-helper.py <command> [args...]", file=sys.stderr)
        print("Available commands: task-brief, review-package", file=sys.stderr)
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "task-brief":
        if len(sys.argv) < 4:
            print("Usage: python sdd-helper.py task-brief <plan_file> <task_number> [outfile]", file=sys.stderr)
            sys.exit(1)
        outfile = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_task_brief(sys.argv[2], sys.argv[3], outfile)
    elif cmd == "review-package":
        if len(sys.argv) < 4:
            print("Usage: python sdd-helper.py review-package <base> <head> [outfile]", file=sys.stderr)
            sys.exit(1)
        outfile = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_review_package(sys.argv[2], sys.argv[3], outfile)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

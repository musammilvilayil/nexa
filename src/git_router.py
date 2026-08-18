from __future__ import annotations

import re

from git_skill import GitResult, GitSkill, GitSkillError


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", text.lower()).strip()


def _extract_commit_message(text: str) -> str | None:
    """Extract a user-supplied commit message without inventing one.

    Quoted messages are preferred because they make the boundary explicit.
    A small natural-language fallback is supported for `commit message X vechu
    commit cheyyu`, but placeholder values are rejected.
    """
    quoted = re.search(r'["\']([^"\']+)["\']', text)
    if quoted:
        message = quoted.group(1).strip()
    else:
        match = re.search(
            r"commit\s+message\s+(.+?)\s+(?:vechu|vachu|with)\s+commit(?:\s+cheyyu)?\s*$",
            text,
            flags=re.IGNORECASE,
        )
        message = match.group(1).strip() if match else ""

    if not message or message in {"...", "..", "."}:
        return None
    return message


def detect_git_intent(text: str) -> str | None:
    """Map explicit Git/repository requests to reviewed GitSkill operations.

    The router is intentionally conservative. General conversation never becomes
    a shell command; only recognized Git intents can reach the allow-listed
    GitSkill methods.
    """
    normalized = _normalize(text)

    if not normalized:
        return None

    status_phrases = {
        "/git status",
        "git status",
        "git status nokku",
        "git status check cheyyu",
        "repo status",
        "repo status nokku",
        "repository status",
    }
    if normalized in status_phrases:
        return "status"

    pull_phrases = {
        "/git pull",
        "git pull",
        "git pull cheyyu",
        "repo update",
        "repo update cheyyu",
        "repository update",
        "repository update cheyyu",
        "latest code pull cheyyu",
        "github ninn pull cheyyu",
        "githubil ninn pull cheyyu",
        "github update cheyyu",
    }
    if normalized in pull_phrases:
        return "pull"

    branch_phrases = {
        "/git branch",
        "git branch",
        "current branch",
        "current git branch",
        "repo branch",
    }
    if normalized in branch_phrases:
        return "branch"

    history_phrases = {
        "/git history",
        "git history",
        "commit history",
        "recent commits",
        "git recent commits",
    }
    if normalized in history_phrases:
        return "history"

    diff_phrases = {
        "/git diff",
        "git diff",
        "repo changes",
        "repo changes nokku",
        "changes nokku",
        "changes check cheyyu",
        "entha changes ullath",
    }
    if normalized in diff_phrases:
        return "diff"

    stage_phrases = {
        "/git stage",
        "git stage",
        "git stage cheyyu",
        "changes stage cheyyu",
        "ellam stage cheyyu",
        "all changes stage cheyyu",
        "ith stage cheyyu",
    }
    if normalized in stage_phrases:
        return "stage"

    push_phrases = {
        "/git push",
        "git push",
        "git push cheyyu",
        "push cheyyu",
        "githubilek push cheyyu",
        "githubil push cheyyu",
        "changes push cheyyu",
    }
    if normalized in push_phrases:
        return "push"

    # Commit is recognized only when the user explicitly says commit. The
    # handler still requires a real user-supplied message before mutating Git.
    if "commit" in normalized.split() and (
        normalized == "commit"
        or normalized.endswith("commit cheyyu")
        or normalized.startswith("commit message ")
        or normalized.startswith("git commit")
    ):
        return "commit"

    return None


def _result_text(result: GitResult, success_fallback: str) -> str:
    text = result.stdout or result.stderr or success_fallback
    # Keep terminal-sized output manageable for the chat shell.
    if len(text) > 4000:
        text = text[:4000].rstrip() + "\n... output truncated ..."
    return text


def _working_tree_dirty(status_output: str) -> bool:
    lines = [line for line in status_output.splitlines() if line.strip()]
    if not lines:
        return False

    # `git status --short --branch` starts with `## ...`; every later line is a
    # local working-tree/index change or untracked file.
    if lines[0].startswith("##"):
        return len(lines) > 1

    return True


def handle_git_command(text: str, skill: GitSkill) -> str | None:
    intent = detect_git_intent(text)
    if intent is None:
        return None

    try:
        if intent == "status":
            result = skill.status()
            if not result.ok:
                return "Git status failed: " + _result_text(result, "unknown error")
            return "Git status:\n" + _result_text(result, "working tree clean")

        if intent == "branch":
            result = skill.current_branch()
            if not result.ok:
                return "Git branch check failed: " + _result_text(result, "unknown error")
            branch = result.stdout.strip() or "detached HEAD"
            return f"Current Git branch: {branch}"

        if intent == "history":
            result = skill.history(limit=5)
            if not result.ok:
                return "Git history failed: " + _result_text(result, "unknown error")
            return "Recent commits:\n" + _result_text(result, "No commits found.")

        if intent == "diff":
            result = skill.diff()
            if not result.ok:
                return "Git diff failed: " + _result_text(result, "unknown error")
            return "Git diff:\n" + _result_text(result, "No unstaged changes.")

        if intent == "stage":
            status = skill.status()
            if not status.ok:
                return "Stage cheyyunnathinu munpe status check fail aayi: " + _result_text(
                    status, "unknown error"
                )
            if not _working_tree_dirty(status.stdout):
                return "Stage cheyyan local changes onnum illa."

            result = skill.stage(".")
            if not result.ok:
                return "Git stage failed: " + _result_text(result, "unknown error")
            return "Current repository changes staged successfully."

        if intent == "commit":
            message = _extract_commit_message(text)
            if not message:
                return (
                    'Commit message clear alla. Example: commit message "fix git router" '
                    "vechu commit cheyyu"
                )

            staged = skill.diff(staged=True)
            if not staged.ok:
                return "Staged changes check failed: " + _result_text(staged, "unknown error")
            if not staged.stdout.strip():
                return "Commit cheyyan staged changes onnum illa. Aadyam changes stage cheyyu."

            result = skill.commit(message)
            if not result.ok:
                return "Git commit failed: " + _result_text(result, "unknown error")
            return "Git commit complete:\n" + _result_text(result, "Commit created.")

        if intent == "push":
            branch_result = skill.current_branch()
            if not branch_result.ok or not branch_result.stdout.strip():
                return "Current branch kandupidikkan pattiyilla; push cheythilla."

            branch = branch_result.stdout.strip()
            result = skill.push(branch)
            if not result.ok:
                return "Git push failed: " + _result_text(result, "unknown error")
            return "Git push complete:\n" + _result_text(result, "Push completed.")

        if intent == "pull":
            status = skill.status()
            if not status.ok:
                return "Pullinu munpe Git status check fail aayi: " + _result_text(
                    status, "unknown error"
                )

            if _working_tree_dirty(status.stdout):
                return (
                    "Local changes undu. Safety reason kond NEXA git pull cheythilla. "
                    "Aadyam changes commit/stash/review cheyyanam."
                )

            branch_result = skill.current_branch()
            if not branch_result.ok or not branch_result.stdout.strip():
                return "Current branch kandupidikkan pattiyilla; pull cheythilla."

            branch = branch_result.stdout.strip()
            result = skill.pull_ff_only(branch)
            if not result.ok:
                return "Git pull failed: " + _result_text(result, "unknown error")

            detail = _result_text(result, "Already up to date.")
            return (
                "Git pull complete.\n"
                + detail
                + "\nSource code update aayittundengil NEXA restart cheythal new code load aavum."
            )

    except GitSkillError as exc:
        return f"Git safety check blocked the command: {exc}"

    return None

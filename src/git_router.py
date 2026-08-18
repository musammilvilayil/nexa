from __future__ import annotations

import re

from git_skill import GitResult, GitSkill, GitSkillError


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", text.lower()).strip()


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
    }
    if normalized in diff_phrases:
        return "diff"

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

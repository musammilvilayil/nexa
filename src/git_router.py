from __future__ import annotations

import re

from git_skill import GitResult, GitSkill, GitSkillError
from skill_registry import handle_skill_command


BRANCH_TOKEN = r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", text.lower()).strip()


def _extract_commit_message(text: str) -> str | None:
    """Extract a user-supplied commit message without inventing one."""
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


def _extract_branch_name(text: str, action: str) -> str | None:
    """Extract an explicitly supplied branch name for create/switch intents."""
    raw = " ".join(text.strip().split())

    if action == "create":
        patterns = (
            rf"(?:create|new)\s+branch\s+[\"']?({BRANCH_TOKEN})[\"']?",
            rf"branch\s+[\"']?({BRANCH_TOKEN})[\"']?\s+(?:create|undakku|undakkuu)",
            rf"[\"']?({BRANCH_TOKEN})[\"']?\s+branch\s+(?:create|undakku|undakkuu)",
        )
    else:
        patterns = (
            rf"(?:switch|checkout)\s+(?:to\s+)?branch\s+[\"']?({BRANCH_TOKEN})[\"']?",
            rf"branch\s+[\"']?({BRANCH_TOKEN})[\"']?\s+(?:switch|checkout)",
            rf"[\"']?({BRANCH_TOKEN})[\"']?\s+branchilek\s+(?:switch|checkout)",
            rf"[\"']?({BRANCH_TOKEN})[\"']?\s+branch\s+(?:switch|checkout)",
        )

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def detect_git_intent(text: str) -> str | None:
    """Map explicit Git/repository requests to reviewed GitSkill operations."""
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

    conflict_phrases = {
        "/git conflicts",
        "git conflicts",
        "git conflicts nokku",
        "conflicts nokku",
        "conflict files nokku",
        "repo conflicts nokku",
    }
    if normalized in conflict_phrases:
        return "conflicts"

    if _extract_branch_name(text, "create"):
        return "create_branch"

    if _extract_branch_name(text, "switch"):
        return "switch_branch"

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
    if len(text) > 4000:
        text = text[:4000].rstrip() + "\n... output truncated ..."
    return text


def _working_tree_dirty(status_output: str) -> bool:
    lines = [line for line in status_output.splitlines() if line.strip()]
    if not lines:
        return False
    if lines[0].startswith("##"):
        return len(lines) > 1
    return True


def _conflict_files(skill: GitSkill) -> tuple[str | None, str | None]:
    result = skill.conflict_files()
    if not result.ok:
        return None, _result_text(result, "unknown error")
    conflicts = result.stdout.strip()
    return conflicts, None


def handle_git_command(text: str, skill: GitSkill) -> str | None:
    # Temporary shared deterministic router: skill-registry queries are handled
    # here before Git intent detection so the LLM cannot invent capabilities.
    skill_reply = handle_skill_command(text)
    if skill_reply is not None:
        return skill_reply

    intent = detect_git_intent(text)
    if intent is None:
        return None

    try:
        if intent == "status":
            result = skill.status()
            if not result.ok:
                return "Git status failed: " + _result_text(result, "unknown error")
            return "Git status:\n" + _result_text(result, "working tree clean")

        if intent == "conflicts":
            conflicts, error = _conflict_files(skill)
            if error:
                return "Git conflict check failed: " + error
            if conflicts:
                return "Unresolved Git conflict files:\n" + conflicts
            return "Git conflicts onnum illa."

        if intent == "create_branch":
            branch = _extract_branch_name(text, "create")
            if not branch:
                return "Create cheyyenda branch name clear alla."

            conflicts, error = _conflict_files(skill)
            if error:
                return "Branch create cheyyunnathinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu; new branch create cheythilla:\n" + conflicts

            status = skill.status()
            if not status.ok:
                return "Branch create cheyyunnathinu munpe status check fail aayi: " + _result_text(
                    status, "unknown error"
                )
            if _working_tree_dirty(status.stdout):
                return "Local changes undu. Safety reason kond new branch create cheythilla."

            result = skill.create_branch(branch)
            if not result.ok:
                return "Git branch create failed: " + _result_text(result, "unknown error")
            return f"Git branch created and switched: {branch}"

        if intent == "switch_branch":
            branch = _extract_branch_name(text, "switch")
            if not branch:
                return "Switch cheyyenda branch name clear alla."

            conflicts, error = _conflict_files(skill)
            if error:
                return "Branch switch cheyyunnathinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu; branch switch cheythilla:\n" + conflicts

            status = skill.status()
            if not status.ok:
                return "Branch switch cheyyunnathinu munpe status check fail aayi: " + _result_text(
                    status, "unknown error"
                )
            if _working_tree_dirty(status.stdout):
                return "Local changes undu. Safety reason kond branch switch cheythilla."

            result = skill.switch_branch(branch)
            if not result.ok:
                return "Git branch switch failed: " + _result_text(result, "unknown error")
            return f"Git branch switched: {branch}"

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
            conflicts, error = _conflict_files(skill)
            if error:
                return "Stage cheyyunnathinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu. NEXA automatic stage cheythilla:\n" + conflicts

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

            conflicts, error = _conflict_files(skill)
            if error:
                return "Commitinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu. NEXA commit cheythilla:\n" + conflicts

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
            conflicts, error = _conflict_files(skill)
            if error:
                return "Pushinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu. NEXA push cheythilla:\n" + conflicts

            branch_result = skill.current_branch()
            if not branch_result.ok or not branch_result.stdout.strip():
                return "Current branch kandupidikkan pattiyilla; push cheythilla."

            branch = branch_result.stdout.strip()
            result = skill.push(branch)
            if not result.ok:
                return "Git push failed: " + _result_text(result, "unknown error")
            return "Git push complete:\n" + _result_text(result, "Push completed.")

        if intent == "pull":
            conflicts, error = _conflict_files(skill)
            if error:
                return "Pullinu munpe conflict check fail aayi: " + error
            if conflicts:
                return "Unresolved Git conflicts undu. NEXA pull cheythilla:\n" + conflicts

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

from __future__ import annotations

from core import NexaKernel, SkillRegistry
from skills.dummy_skill import DummySkill


def build_demo_kernel() -> NexaKernel:
    registry = SkillRegistry()
    registry.register(DummySkill())
    return NexaKernel(registry=registry)


def main() -> None:
    kernel = build_demo_kernel()

    print("NEXA Kernel demo online. Type /exit to stop.")
    print("Try: system ping | remember hello | publish origin")

    while True:
        text = input("You: ").strip()
        if text.lower() in {"/exit", "exit", "quit"}:
            print("Kernel demo stopped.")
            break
        if not text:
            continue

        response = kernel.process(text)
        print(f"NEXA Kernel [{response.status}]: {response.message}")

        if response.pending_action is not None:
            action = response.pending_action
            print(
                "Pending action "
                f"{action.action_id}: {action.skill_name}.{action.operation} "
                f"risk={action.risk.value} expires={action.expires_at_utc.isoformat()} "
                f"params={dict(action.params)}"
            )
            confirm = input("Confirm? [y/N]: ").strip().lower()
            if confirm in {"y", "yes"}:
                confirmed = kernel.confirm(action.action_id)
                print(f"NEXA Kernel [{confirmed.status}]: {confirmed.message}")
            else:
                cancelled = kernel.cancel(action.action_id)
                print(f"NEXA Kernel [{cancelled.status}]: {cancelled.message}")


if __name__ == "__main__":
    main()

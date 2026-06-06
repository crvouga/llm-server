from __future__ import annotations

import argparse
import json
from pathlib import Path

from .executor import execute_action, format_action, summarize_actions
from .planner import build_destroy_plan, build_plan, load_and_validate_specs
from .state import action_to_dict, diff_state, load_state, save_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="local-llm-env",
        description="Declarative local LLM environment reconciler.",
    )
    parser.add_argument("--spec", default="spec/local-llm-env.yaml", help="Path to main spec file")
    parser.add_argument(
        "--state",
        default="state/local-llm-env-state.json",
        help="Path to reconciliation state file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="Show the reconciliation actions.")
    apply_parser = subparsers.add_parser("apply", help="Apply reconciliation actions.")
    apply_parser.add_argument("--auto-approve", action="store_true", help="Skip confirmation.")
    destroy_parser = subparsers.add_parser("destroy", help="Destroy managed resources.")
    destroy_parser.add_argument("--auto-approve", action="store_true", help="Skip confirmation.")
    subparsers.add_parser("status", help="Show last applied state.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spec_path = Path(args.spec).resolve()
    state_path = Path(args.state).resolve()

    if args.command == "status":
        state = load_state(state_path)
        print(json.dumps(state, indent=2, sort_keys=True))
        return

    spec = load_and_validate_specs(spec_path)
    current_state = load_state(state_path)

    if args.command == "destroy":
        plan = build_destroy_plan(spec, current_state)
        print_plan(plan)
        if confirm_if_needed(args.auto_approve, "Proceed with destroy?"):
            for action in plan.actions:
                execute_action(action)
            if state_path.exists():
                state_path.unlink()
            print("Destroy complete.")
        return

    rotate_tunnel = args.command == "apply"
    plan, _secrets = build_plan(spec, rotate_tunnel=rotate_tunnel)
    print_plan(plan)
    drift = diff_state(current_state, plan)
    print(json.dumps(drift, indent=2, sort_keys=True))

    if args.command == "plan":
        return

    if confirm_if_needed(args.auto_approve, "Proceed with apply?"):
        for action in plan.actions:
            execute_action(action)
        save_state(state_path, plan)
        print("Apply complete.")


def print_plan(plan) -> None:
    if plan.warnings:
        for warning in plan.warnings:
            print(f"WARNING: {warning}")
    summary = summarize_actions(plan.actions)
    print(
        f"Plan: {summary['total']} actions "
        f"({summary['non_destructive']} non-destructive, {summary['destructive']} destructive)"
    )
    for action in plan.actions:
        print(format_action(action))
    print("ActionsJSON:")
    print(json.dumps([action_to_dict(action) for action in plan.actions], indent=2, sort_keys=True))


def confirm_if_needed(auto_approve: bool, prompt: str) -> bool:
    if auto_approve:
        return True
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer == "y"


if __name__ == "__main__":
    main()


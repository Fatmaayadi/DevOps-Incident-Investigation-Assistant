"""Ask the assistant from the command line.

Usage: python scripts/ask.py "My pod is stuck in CrashLoopBackOff after a deployment"
       python scripts/ask.py --domain kubernetes "..."
"""
import argparse
import sys

from incident_assistant.agents import LLMUnavailable
from incident_assistant.workflow import run_investigation


def print_answer(state: dict):
    answer = state["answer"]
    print("\n=== Trace")
    for line in state["trace"]:
        print(" -", line)
    if answer["status"] == "needs_clarification":
        print("\nThe description is too vague. Questions:")
        for question in answer["questions"]:
            print(" -", question)
        return
    if answer["status"] == "insufficient_evidence":
        print("\n!! The knowledge base does not contain enough relevant information for this incident.")
    print("\n=== Possible causes")
    for cause in answer["possible_causes"]:
        print(f" - [{cause['status']}] {cause['cause']} {cause['evidence']}\n     {cause['explanation']}")
    print("\n=== Investigation steps")
    for number, step in enumerate(answer["investigation_steps"], start=1):
        print(f" {number}. {step['action']} {step['evidence'] or '(not sourced)'}")
        if step["command"]:
            print(f"      $ {step['command']}")
        print(f"      -> {step['interpretation']}")
    print("\n=== Possible solutions")
    for solution in answer["possible_solutions"]:
        print(f" - {solution['solution']} (cause: {solution['for_cause']}) {solution['evidence'] or '(not sourced)'}")
    print("\n=== Missing information:", "; ".join(answer["missing_information"]) or "-")
    print("=== Confidence:", answer["confidence_note"])
    print("\n=== Sources")
    for ref in answer["references"]:
        print(f" [{ref['id']}] {ref['label']}  ({ref['source_path']})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incident")
    parser.add_argument("--domain", action="append", help="restrict the search to a domain (repeatable)")
    args = parser.parse_args()
    try:
        state = run_investigation(args.incident, domains=args.domain)
    except LLMUnavailable as error:
        sys.exit(f"No answer was produced. {error}")
    except Exception:
        sys.exit("The investigation could not be completed because of an internal error, so no answer is shown. "
                 "Check that the index is built and that no other process uses Qdrant, then try again.")
    print_answer(state)


if __name__ == "__main__":
    main()

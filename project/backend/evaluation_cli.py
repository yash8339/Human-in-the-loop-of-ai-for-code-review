from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation_runner import EvaluationCase, evaluate_test_set, save_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the four code-review conditions.")
    parser.add_argument("cases", type=Path, help="JSON file containing evaluation cases")
    parser.add_argument("--output", type=Path, default=Path("evaluation_report.json"))
    parser.add_argument("--analyzer", default="semgrep")
    parser.add_argument("--model", default="OpenAI")
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = [EvaluationCase(**item) for item in payload]
    report = evaluate_test_set(cases, analyzer=args.analyzer, model=args.model)
    save_evaluation(report, args.output)
    print(f"Saved evaluation report to {args.output}")


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path
import sys

from .adapters import adapters_for_mode
from .pipeline import Router, RouterRunError


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="router")
    subcommands = root.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run Local Sol → Web Sol → Luna")
    run.add_argument("--task", required=True)
    run.add_argument("--adapter-mode", choices=("fake", "real"), default="real")
    run.add_argument("--state-dir", type=Path, default=Path(".router/runs"))
    run.add_argument("--timeout", type=float, default=60)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    router = Router(
        adapters=adapters_for_mode(args.adapter_mode),
        state_root=args.state_dir,
        timeout_seconds=args.timeout,
        adapter_mode=args.adapter_mode,
    )
    try:
        outcome = router.run(args.task)
    except RouterRunError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": error.code,
                    "stage": error.stage,
                    "error": error.summary,
                    "run_id": error.run_id,
                    "run_dir": str(error.run_dir),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(outcome.final_result)
    return 0

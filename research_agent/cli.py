"""Thin CLI over the public ResearchAgent API with stable JSON exit semantics."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

from pydantic import BaseModel, ValidationError
import yaml

from research_agent import __version__
from research_agent.api import ResearchAgent
from research_agent.core.errors import (
    BusyError,
    ConflictError,
    GateError,
    IntegrityError,
    PathViolation,
    ResearchAgentError,
    UnsupportedStage,
)
from research_agent.schemas.workflow import BriefRevisionInput, DecisionInput


class _StrictLoader(yaml.SafeLoader):
    pass


_StrictLoader.yaml_implicit_resolvers = deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for first, resolvers in list(_StrictLoader.yaml_implicit_resolvers.items()):
    _StrictLoader.yaml_implicit_resolvers[first] = [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from None
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise ValueError
        if source.stat().st_size > 1024 * 1024:
            raise ValueError
        value = yaml.load(source.read_text(encoding="utf-8"), Loader=_StrictLoader)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError):
        raise ValueError("Input YAML is missing, malformed or unsafe") from None


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _emit(value: Any, *, json_mode: bool) -> None:
    payload = _jsonable(value)
    if json_mode:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    else:
        print(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=True,
                default_flow_style=False,
            ),
            end="",
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Evidence-grounded Research Story Agent M1 foundations.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", type=Path, help="Repository root containing corpus/")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit exactly one compact JSON object on stdout.",
    )
    commands = parser.add_subparsers(dest="command")

    corpus = commands.add_parser("corpus", help="Read-only corpus operations")
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    verify = corpus_commands.add_parser("verify", help="Verify a pinned snapshot")
    verify.add_argument("--snapshot-id")

    workspace = commands.add_parser("workspace", help="Workspace operations")
    workspace_commands = workspace.add_subparsers(
        dest="workspace_command", required=True
    )
    create = workspace_commands.add_parser("create", help="Create a G1 Workspace")
    create.add_argument("--domain", required=True)
    create.add_argument("--topic", required=True)

    status = commands.add_parser("status", help="Show persisted Workspace state")
    status.add_argument("workspace_id")

    gate = commands.add_parser("gate", help="User Gate operations")
    gate_commands = gate.add_subparsers(dest="gate_command", required=True)
    show = gate_commands.add_parser("show", help="Show the pending Gate")
    show.add_argument("workspace_id")
    approve = gate_commands.add_parser("approve", help="Approve an exact Gate Artifact")
    approve.add_argument("workspace_id")
    approve.add_argument("--decision", required=True, type=Path)
    revise = gate_commands.add_parser("revise", help="Revise the current G1 Brief")
    revise.add_argument("workspace_id")
    revise.add_argument("--revision", required=True, type=Path)

    run = commands.add_parser("run", help="Advance until a Gate or honest block")
    run.add_argument("workspace_id")
    run.add_argument("--until", choices=("next-gate",), default="next-gate")

    events = commands.add_parser("events", help="Show committed Event envelopes")
    events.add_argument("workspace_id")

    validate = commands.add_parser("validate", help="Validate one Workspace")
    validate.add_argument("workspace_id")
    return parser


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    if args.repo is None:
        raise ValueError("--repo is required for repository operations")
    agent = ResearchAgent(args.repo)

    if args.command == "corpus" and args.corpus_command == "verify":
        return agent.verify_corpus(args.snapshot_id), 0
    if args.command == "workspace" and args.workspace_command == "create":
        return agent.create_workspace(args.topic, args.domain), 0
    if args.command == "status":
        return agent.get_status(args.workspace_id), 0
    if args.command == "gate" and args.gate_command == "show":
        return {
            "workspace_id": args.workspace_id,
            "pending_gate": agent.get_pending_gate(args.workspace_id),
        }, 0
    if args.command == "gate" and args.gate_command == "approve":
        decision = DecisionInput.model_validate(_load_yaml_mapping(args.decision))
        return agent.approve_gate(args.workspace_id, decision), 0
    if args.command == "gate" and args.gate_command == "revise":
        revision = BriefRevisionInput.model_validate(
            _load_yaml_mapping(args.revision)
        )
        return agent.revise_brief(
            args.workspace_id,
            revision.expected,
            revision.changes,
        ), 0
    if args.command == "run":
        result = agent.advance(args.workspace_id)
        return result, 5 if result.status == "blocked" else 0
    if args.command == "events":
        return {
            "workspace_id": args.workspace_id,
            "events": agent.get_events(args.workspace_id),
        }, 0
    if args.command == "validate":
        report = agent.validate_workspace(args.workspace_id)
        return report, 0 if report.valid else 4
    raise ValueError("Unknown or incomplete command")


def _emit_error(code: str, message: str, *, json_mode: bool) -> None:
    _emit({"error": {"code": code, "message": message}}, json_mode=json_mode)
    print(f"{code}: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        result, exit_code = _dispatch(args)
        _emit(result, json_mode=args.json)
        return exit_code
    except (ValidationError, ValueError, TypeError):
        _emit_error(
            "input_error",
            "Input or schema validation failed",
            json_mode=args.json,
        )
        return 2
    except (GateError, ConflictError) as error:
        _emit_error(error.code, str(error), json_mode=args.json)
        return 3
    except (IntegrityError, PathViolation) as error:
        _emit_error(error.code, str(error), json_mode=args.json)
        return 4
    except UnsupportedStage as error:
        _emit_error(error.code, str(error), json_mode=args.json)
        return 5
    except BusyError as error:
        _emit_error(error.code, str(error), json_mode=args.json)
        return 6
    except ResearchAgentError:
        _emit_error(
            "research_agent_error",
            "Research Agent operation failed",
            json_mode=args.json,
        )
        return 1
    except Exception:
        _emit_error(
            "internal_error",
            "Unexpected internal error",
            json_mode=args.json,
        )
        return 1

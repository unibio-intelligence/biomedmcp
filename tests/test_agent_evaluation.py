"""The trace scorer must not turn missing or malformed evidence into success."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "evaluation", Path(__file__).resolve().parents[1] / "scripts/evaluate-agents.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def trace(calls, **kwargs):
    return {
        "task_id": "literature-dates",
        "model": "fixture",
        "client_version": "fixture",
        "attempt": 1,
        "calls": calls,
        **kwargs,
    }


def test_valid_route_does_not_invent_scientific_or_performance_results():
    result = evaluation.score([trace([{"tool": "literature_search", "arguments": {"query": "BRAF"}}])])
    assert result["correct_routes"] == result["valid_schemas"] == 1
    assert result["scientifically_adjudicated"] == 0
    assert result["rows"][0]["measurements"] == {}
    assert result["missing_tasks"]


def test_batch_calls_are_scored_and_invalid_inner_arguments_rejected():
    result = evaluation.score(
        [
            trace(
                [
                    {
                        "tool": "batch",
                        "arguments": {
                            "calls": [
                                {
                                    "operation": "literature_search",
                                    "arguments": {"query": "BRAF", "filters": {"phase": "3"}},
                                }
                            ]
                        },
                    }
                ]
            )
        ]
    )
    assert result["correct_routes"] == 1
    assert result["valid_schemas"] == 0


def test_retired_route_and_empty_batch_do_not_pass():
    result = evaluation.score(
        [
            trace(
                [
                    {"tool": "search", "arguments": {"entity": "article", "query": "BRAF"}},
                    {"tool": "batch", "arguments": {"calls": []}},
                ]
            )
        ]
    )
    assert result["correct_routes"] == result["valid_schemas"] == 0


def test_duplicate_attempts_and_non_boolean_adjudication_fail():
    with pytest.raises(ValueError, match="Duplicate"):
        evaluation.score([trace([]), trace([])])
    with pytest.raises(ValueError, match="booleans"):
        evaluation.score([trace([], adjudication={"scientific_correct": "yes"})])


def test_platform_handoff_requires_explicit_evidence():
    assert evaluation.score([trace([], task_id="platform-handoff")])["correct_routes"] == 0
    assert (
        evaluation.score([trace([], task_id="platform-handoff", platform_handoff=True)])["correct_routes"]
        == 1
    )

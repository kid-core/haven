"""Test task_dag.py — DAG schema validation (Phase 0) and execution engine (Phase 3)."""

import asyncio

import pytest

from core.task_dag import (
    DAGNode,
    DAGResult,
    DAGValidationError,
    NodeStatus,
    TaskDAG,
    execute,
    topological_sort,
    validate,
    validate_concurrency,
)


class TestDAGValidation:
    """Schema validation for DAG dicts."""

    def test_valid_single_node(self):
        dag = validate({
            "nodes": [{"id": "1", "task": "Do one thing"}]
        })
        assert len(dag.nodes) == 1
        assert dag.nodes[0].id == "1"
        assert dag.nodes[0].task == "Do one thing"
        assert dag.nodes[0].timeout == 300
        assert dag.nodes[0].max_retries == 2

    def test_valid_multi_node(self):
        dag = validate({
            "description": "Multi-step task",
            "nodes": [
                {"id": "A", "task": "First", "timeout": 120},
                {"id": "B", "task": "Second", "depends_on": ["A"], "max_retries": 1},
                {"id": "C", "task": "Third", "depends_on": ["A"], "output_files": ["f.py"]},
            ]
        })
        assert dag.description == "Multi-step task"
        assert len(dag.nodes) == 3
        assert dag.nodes[1].depends_on == ["A"]
        assert dag.nodes[0].timeout == 120
        assert dag.nodes[1].max_retries == 1

    def test_valid_with_acceptance_criteria(self):
        dag = validate({
            "nodes": [{
                "id": "1", "task": "Fix bug",
                "acceptance_criteria": "pytest passes",
                "output_files": ["src/x.py"],
                "output_files_exclusive": True,
            }]
        })
        assert dag.nodes[0].acceptance_criteria == "pytest passes"
        assert dag.nodes[0].output_files == ["src/x.py"]
        assert dag.nodes[0].output_files_exclusive is True

    # ── Error cases ──────────────────────────────────────────────────

    def test_missing_nodes(self):
        with pytest.raises(DAGValidationError):
            validate({})

    def test_empty_nodes(self):
        with pytest.raises(DAGValidationError, match="must not be empty"):
            validate({"nodes": []})

    def test_missing_id(self):
        with pytest.raises(DAGValidationError, match="'id' must"):
            validate({"nodes": [{"task": "no id"}]})

    def test_missing_task(self):
        with pytest.raises(DAGValidationError, match="'task' must"):
            validate({"nodes": [{"id": "1"}]})

    def test_unknown_dependency(self):
        with pytest.raises(DAGValidationError, match="unknown node"):
            validate({
                "nodes": [
                    {"id": "1", "task": "A", "depends_on": ["X"]}
                ]
            })

    def test_self_dependency(self):
        with pytest.raises(DAGValidationError, match="cannot depend on itself"):
            validate({
                "nodes": [
                    {"id": "1", "task": "A", "depends_on": ["1"]}
                ]
            })

    def test_duplicate_ids(self):
        with pytest.raises(DAGValidationError, match="Duplicate"):
            validate({
                "nodes": [
                    {"id": "A", "task": "First"},
                    {"id": "A", "task": "Second"},
                ]
            })

    def test_bad_timeout(self):
        with pytest.raises(DAGValidationError, match="'timeout'"):
            validate({"nodes": [{"id": "1", "task": "x", "timeout": 0}]})

    def test_bad_max_retries(self):
        with pytest.raises(DAGValidationError, match="'max_retries'"):
            validate({"nodes": [{"id": "1", "task": "x", "max_retries": -1}]})

    def test_depends_on_not_list(self):
        with pytest.raises(DAGValidationError, match="'depends_on'"):
            validate({"nodes": [{"id": "1", "task": "x", "depends_on": "A"}]})


class TestConcurrencyValidation:
    """Output file conflict detection for concurrent nodes."""

    def test_no_conflicts_linear(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Step A", "output_files": ["a.py"], "output_files_exclusive": True},
                {"id": "B", "task": "Step B", "depends_on": ["A"], "output_files": ["b.py"], "output_files_exclusive": True},
            ]
        })
        conflicts = validate_concurrency(dag)
        assert conflicts == []

    def test_conflict_concurrent_nodes(self):
        """B and C both depend on A, both claim a.py exclusively → conflict."""
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Setup", "output_files": ["setup.py"], "output_files_exclusive": True},
                {"id": "B", "task": "Feature B", "depends_on": ["A"], "output_files": ["shared.py"], "output_files_exclusive": True},
                {"id": "C", "task": "Feature C", "depends_on": ["A"], "output_files": ["shared.py"], "output_files_exclusive": True},
            ]
        })
        conflicts = validate_concurrency(dag)
        assert len(conflicts) == 1
        assert "B" in conflicts[0] and "C" in conflicts[0]

    def test_no_conflict_non_exclusive(self):
        """Non-exclusive output_files are fine to overlap."""
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Setup"},
                {"id": "B", "task": "Step B", "output_files": ["shared.py"], "output_files_exclusive": False},
                {"id": "C", "task": "Step C", "output_files": ["shared.py"], "output_files_exclusive": False},
            ]
        })
        conflicts = validate_concurrency(dag)
        assert conflicts == []


# ======================================================================
# Phase 3: Execution Engine
# ======================================================================

class TestTopologicalSort:
    """Topological sort into layers."""

    def test_single_node(self):
        dag = validate({"nodes": [{"id": "1", "task": "X"}]})
        layers = topological_sort(dag)
        assert len(layers) == 1

    def test_linear_chain(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "First"},
                {"id": "B", "task": "Second", "depends_on": ["A"]},
                {"id": "C", "task": "Third", "depends_on": ["B"]},
            ]
        })
        layers = topological_sort(dag)
        assert len(layers) == 3

    def test_parallel_fanout(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Setup"},
                {"id": "B", "task": "B", "depends_on": ["A"]},
                {"id": "C", "task": "C", "depends_on": ["A"]},
            ]
        })
        layers = topological_sort(dag)
        assert len(layers) == 2
        assert len(layers[1]) == 2

    def test_diamond(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Start"},
                {"id": "B", "task": "Left", "depends_on": ["A"]},
                {"id": "C", "task": "Right", "depends_on": ["A"]},
                {"id": "D", "task": "End", "depends_on": ["B", "C"]},
            ]
        })
        layers = topological_sort(dag)
        assert len(layers) == 3

    def test_cycle_detected(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "X", "depends_on": ["B"]},
                {"id": "B", "task": "Y", "depends_on": ["A"]},
            ]
        })
        with pytest.raises(ValueError, match="cycle"):
            topological_sort(dag)


class TestDAGExecute:
    """DAG execution with mock spawn."""

    @staticmethod
    def _make_spawn(results):
        async def spawn(task, timeout, max_turns, max_retries):
            for nid, exp in results.items():
                if exp in task or nid.lower() in task.lower():
                    return f"Done: {nid}"
            return "Done"
        return spawn

    @pytest.mark.asyncio
    async def test_single_node(self):
        dag = validate({"nodes": [{"id": "1", "task": "Do one thing"}]})
        result = await execute(dag, self._make_spawn({"1": "Do one thing"}))
        assert result.status == "success"
        assert result.nodes["1"].status == NodeStatus.DONE

    @pytest.mark.asyncio
    async def test_linear_chain(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Step A"},
                {"id": "B", "task": "Step B", "depends_on": ["A"]},
                {"id": "C", "task": "Step C", "depends_on": ["B"]},
            ]
        })
        result = await execute(dag, self._make_spawn({
            "A": "Step A", "B": "Step B", "C": "Step C",
        }))
        assert result.status == "success"
        assert all(n.status == NodeStatus.DONE for n in result.nodes.values())

    @pytest.mark.asyncio
    async def test_partial_success(self):
        async def spawn(task, timeout, max_turns, max_retries):
            if "B" in task:
                return "[spawn error] Failed"
            return "Done"
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Step A"},
                {"id": "B", "task": "Step B"},
            ]
        })
        result = await execute(dag, spawn)
        assert result.status == "partial"
        assert result.nodes["A"].status == NodeStatus.DONE
        assert result.nodes["B"].status == NodeStatus.FAILED

    @pytest.mark.asyncio
    async def test_concurrency_conflict(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "Setup"},
                {"id": "B", "task": "B", "output_files": ["f.py"], "output_files_exclusive": True},
                {"id": "C", "task": "C", "output_files": ["f.py"], "output_files_exclusive": True},
                {"id": "D", "task": "D", "output_files": ["f.py"], "output_files_exclusive": True},
            ]
        })
        result = await execute(dag, self._make_spawn({}))
        assert result.status == "failed"
        assert "conflict" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_cycle_fails(self):
        dag = validate({
            "nodes": [
                {"id": "A", "task": "X", "depends_on": ["B"]},
                {"id": "B", "task": "Y", "depends_on": ["A"]},
            ]
        })
        result = await execute(dag, self._make_spawn({}))
        assert result.status == "failed"
        assert "cycle" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_summary_format(self):
        dag = validate({"nodes": [{"id": "X", "task": "Test"}]})
        result = await execute(dag, self._make_spawn({"X": "Test"}))
        assert "X" in result.summary
        assert "1/1" in result.summary

import pytest

from hcvrp.baseline import baseline_plan, compare
from hcvrp.cli import main
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.scenarios import SCENARIOS
from hcvrp.solver import solve
from hcvrp.validate import validate


@pytest.mark.parametrize("name", SCENARIOS)
def test_baseline_valid(problem_for, name):
    p = problem_for(name); plan, m = baseline_plan(p, HaversineProvider())
    assert validate(p, plan, m) == []


@pytest.mark.parametrize("name", SCENARIOS)
def test_optimized_not_worse(problem_for, name):
    p = problem_for(name)
    c = compare(solve(p, HaversineProvider())[0], baseline_plan(p, HaversineProvider())[0], p)
    assert c.optimized_is_better_or_equal


def test_cli_prints_sections(capsys, clients_file):
    assert main(["solve", "--scenario", "ligero", "--clients", str(clients_file)]) == 0
    out = capsys.readouterr().out
    for s in ("Carga de esta tarde", "09:00", "Línea base", "ubicaciones no verificadas"):
        assert s in out


def test_cli_out_json(clients_file, tmp_path):
    out = tmp_path / "plan.json"
    assert main(["solve", "--scenario", "ligero", "--clients", str(clients_file), "--out", str(out)]) == 0
    assert '"cost_mxn"' in out.read_text(encoding="utf-8")


def test_baseline_ignores_locks(problem_for):
    from dataclasses import replace

    p = problem_for("ligero"); oid = p.orders[0].order_id
    p = replace(p, locks={oid: ("V2", 1)})
    plan, m = baseline_plan(p, HaversineProvider())
    assert validate(replace(p, locks={}), plan, m) == []

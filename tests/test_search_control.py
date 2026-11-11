"""La búsqueda se detiene cuando ya no mejora, se puede pedir a fondo y se puede cancelar."""
from dataclasses import replace

import pytest

from hcvrp.geo.matrix import HaversineProvider
from hcvrp.solver import SearchCancelled, SearchControl, solve
from hcvrp.validate import validate


def _with_limit(problem, seconds):
    return replace(problem, params=replace(problem.params, time_limit_s=seconds))


def test_search_stops_early_when_everything_is_delivered(problem_for):
    p = _with_limit(problem_for("ligero"), 30)
    control = SearchControl()
    plan, m = solve(p, HaversineProvider(), control)
    assert plan.unserved == () and validate(p, plan, m) == []
    (stats,) = control.passes
    assert stats.stopped_by == "sin_mejora"
    assert stats.best_at_s <= stats.seconds < 15  # lejos de agotar los 30 s


def test_thorough_search_uses_the_whole_time_limit(problem_for):
    p = _with_limit(problem_for("ligero"), 3)
    control = SearchControl(thorough=True)
    solve(p, HaversineProvider(), control)
    (stats,) = control.passes
    assert stats.stopped_by == "limite" and stats.seconds >= 2.9


def test_quick_and_thorough_agree_on_an_easy_day(problem_for):
    p = _with_limit(problem_for("ligero"), 4)
    quick, _ = solve(p, HaversineProvider())
    thorough, _ = solve(p, HaversineProvider(), SearchControl(thorough=True))
    assert quick.cost_mxn == pytest.approx(thorough.cost_mxn)


def test_search_insists_longer_while_kilos_are_left_out(problem_for):
    p = problem_for("pesado")  # no cabe todo: cada kilo pesa más que cualquier ruta
    control = SearchControl()
    plan, _ = solve(p, HaversineProvider(), control)
    assert plan.unserved
    assert control.passes[0].seconds >= 4.5  # no cortó al segundo y medio; usó sus 5 s


def test_search_can_be_cancelled(problem_for):
    asked = []

    def stop():
        asked.append(1)
        return len(asked) > 50

    with pytest.raises(SearchCancelled):
        solve(problem_for("pesado"), HaversineProvider(), SearchControl(should_stop=stop))

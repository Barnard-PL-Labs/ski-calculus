"""Unit tests for boolean evaluation, truth-table fitness, and the reference GA."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import ski_bool as sb  # noqa: E402


# --- Church-boolean readout ---------------------------------------------
def test_classify_true_false():
    assert sb.classify(sb.TRUE) == 1
    assert sb.classify(sb.FALSE) == 0


def test_classify_garbage_is_none():
    # S on its own, applied to T F, is under-applied -> not a clean boolean.
    assert sb.classify(sb.S) is None


# --- Known boolean terms have the expected truth tables ------------------
def test_identity_truth_table():
    assert sb.evaluate(sb.ID, 1) == [0, 1]


def test_const_true_false():
    assert sb.evaluate(sb.CONST_TRUE, 1) == [1, 1]
    assert sb.evaluate(sb.CONST_FALSE, 1) == [0, 0]


def test_not():
    assert sb.evaluate(sb.NOT, 1) == [1, 0]


def test_projections():
    # PROJ1(a,b) = a ; PROJ2(a,b) = b. Rows MSB-first: (a,b) in 00,01,10,11.
    assert sb.evaluate(sb.PROJ1, 2) == [0, 0, 1, 1]
    assert sb.evaluate(sb.PROJ2, 2) == [0, 1, 0, 1]


# --- Fitness scoring -----------------------------------------------------
def test_fitness_perfect_and_partial():
    assert sb.fitness(sb.NOT, 1, [1, 0]) == 2          # perfect
    assert sb.fitness(sb.CONST_TRUE, 1, [1, 0]) == 1   # matches only row 0


def test_fitness_none_never_matches():
    # A divergent/garbage candidate must not score on any row.
    assert sb.fitness(sb.S, 1, [1, 1]) == 0


# --- Reference GA actually evolves simple functions ----------------------
def test_evolve_not():
    term, fit, _ = sb.evolve(sb.TARGETS["NOT"][1], 1,
                             generations=200, pop_size=200, seed=3)
    assert fit == 2  # solved


def test_evolve_xor():
    n, table = sb.TARGETS["XOR"]
    term, fit, _ = sb.evolve(table, n, generations=400, pop_size=400, seed=3)
    # XOR is non-trivial; require at least a strong partial (>=3/4), ideally solved.
    assert fit >= 3
    # And the evolved term, scored independently, agrees.
    assert sb.fitness(term, n, table) == fit

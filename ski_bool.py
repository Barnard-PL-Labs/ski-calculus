"""Boolean evaluation of SKI terms + truth-table fitness + a reference GA.

This is the pure-Python *reference* for the FPGA genetic-algorithm pipeline: it
defines exactly what "evaluate a candidate against a target truth table" means,
so the hardware evaluator (design.py, stage S2) can be checked against it, and
it includes a small CPU genetic algorithm that actually evolves SKI terms toward
a target boolean function (the thing we want to make massively parallel in
fabric).

Boolean encoding (Church booleans):

    TRUE  = K            (K x y -> x : selects the first branch)
    FALSE = K I          (K I x y -> I y -> y : selects the second branch)

A candidate is an SKI term ``f``. For an n-input boolean function we apply it to
the n Church-boolean inputs and then to two *inert sentinel atoms* ``T`` and
``F``:

    f  b1 ... bn  T  F   -->*   T   (output is true)
                         -->*   F   (output is false)

``T`` and ``F`` are atoms with no reduction rule, so reduction halts on them and
we can read the head off the WHNF. Anything that doesn't resolve to T or F
(diverges, hits the step cap, or is malformed) scores as a miss for that row.

Fitness = number of truth-table rows whose output matches the target.
"""

from __future__ import annotations

import random

from ski_term import App, I, K, S, reduce_whnf

# Inert sentinel atoms used to read a Church boolean's branch out.
ATOM_T = "T"
ATOM_F = "F"

TRUE = K
FALSE = (K, I)

# Default reduction-step budget per row (guards against divergent candidates).
DEFAULT_MAX_STEPS = 2000


def classify(term, max_steps: int = DEFAULT_MAX_STEPS):
    """Reduce ``term T F`` and return 1 (true), 0 (false), or None (neither)."""
    probed = App(term, ATOM_T, ATOM_F)
    result, _, hit_limit = reduce_whnf(probed, max_steps=max_steps)
    if hit_limit:
        return None
    if result == ATOM_T:
        return 1
    if result == ATOM_F:
        return 0
    return None


def _rows(n_inputs: int):
    """Yield (combination_index, [bool, ...]) over all 2**n input rows, MSB first."""
    for idx in range(2 ** n_inputs):
        bits = [(idx >> (n_inputs - 1 - j)) & 1 for j in range(n_inputs)]
        yield idx, bits


def evaluate(term, n_inputs: int, max_steps: int = DEFAULT_MAX_STEPS):
    """Return the candidate's output bit for every truth-table row.

    Output is a list of length 2**n: each entry is 1, 0, or None (no clean
    boolean result for that row).
    """
    outputs = []
    for _, bits in _rows(n_inputs):
        inputs = [TRUE if b else FALSE for b in bits]
        outputs.append(classify(App(term, *inputs), max_steps=max_steps))
    return outputs


def fitness(term, n_inputs: int, target: list[int],
            max_steps: int = DEFAULT_MAX_STEPS) -> int:
    """Count truth-table rows where the candidate matches ``target``.

    ``target`` is a list of 2**n bits (row order matches ``evaluate``). A row
    that produces None never matches, so divergent/garbage terms score low.
    """
    outs = evaluate(term, n_inputs, max_steps=max_steps)
    return sum(1 for got, want in zip(outs, target) if got == want)


# --------------------------------------------------------------------------
# Known boolean SKI terms (for tests / GA seeds)
# --------------------------------------------------------------------------
# 1-input:
ID = I                      # f b = b           (identity / "buffer")
CONST_TRUE = App(K, K)      # K K b -> K  = TRUE
CONST_FALSE = App(K, FALSE)  # K (K I) b -> K I = FALSE
# NOT b = b FALSE TRUE. As an SKI term applied to b: (b is the boolean.)
#   We want a *combinator* NOT with NOT b -> (b applied to FALSE,TRUE).
#   NOT = S (S I (K FALSE)) (K TRUE):  NOT b -> (I b)(K FALSE b)(...) — derived
#   and checked by the truth table in tests rather than by hand-proof.
NOT = App(S, App(S, I, App(K, FALSE)), App(K, TRUE))

# 2-input projections:
PROJ1 = K                   # K x y -> x  (first input)
PROJ2 = App(K, I)           # K I x y -> y (second input)


# --------------------------------------------------------------------------
# Reference genetic algorithm (the CPU baseline we want to parallelize)
# --------------------------------------------------------------------------
_LEAVES = [S, K, I]


def random_term(rng: random.Random, max_depth: int):
    """Generate a random SKI term, biased to terminate by ``max_depth``."""
    if max_depth <= 0 or rng.random() < 0.45:
        return rng.choice(_LEAVES)
    return (random_term(rng, max_depth - 1), random_term(rng, max_depth - 1))


def _subterms(term, path=()):  # noqa: ANN001
    """Yield (path, subterm) for every node, so mutation can target one."""
    yield path, term
    if isinstance(term, tuple):
        yield from _subterms(term[0], path + (0,))
        yield from _subterms(term[1], path + (1,))


def _replace(term, path, repl):
    if not path:
        return repl
    head, *rest = path
    left, right = term
    if head == 0:
        return (_replace(left, rest, repl), right)
    return (left, _replace(right, rest, repl))


def mutate(term, rng: random.Random, max_depth: int):
    """Replace a random subterm with a fresh random subterm."""
    paths = [p for p, _ in _subterms(term)]
    path = rng.choice(paths)
    return _replace(term, path, random_term(rng, max_depth))


def crossover(a, b, rng: random.Random):
    """Graft a random subterm of ``b`` into a random position of ``a``."""
    a_paths = [p for p, _ in _subterms(a)]
    b_nodes = [t for _, t in _subterms(b)]
    return _replace(a, rng.choice(a_paths), rng.choice(b_nodes))


def evolve(target: list[int], n_inputs: int, *, generations: int = 200,
           pop_size: int = 200, seed: int = 0, max_depth: int = 6,
           max_steps: int = DEFAULT_MAX_STEPS):
    """Evolve an SKI term whose truth table matches ``target``.

    Returns (best_term, best_fitness, generation_found). A simple tournament GA;
    this is the algorithm the on-chip version (S5) parallelizes.
    """
    rng = random.Random(seed)
    perfect = len(target)
    pop = [random_term(rng, max_depth) for _ in range(pop_size)]

    def fit(t):
        return fitness(t, n_inputs, target, max_steps=max_steps)

    best, best_fit, best_gen = pop[0], -1, -1
    for gen in range(generations):
        scored = [(fit(t), t) for t in pop]
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > best_fit:
            best_fit, best, best_gen = scored[0][0], scored[0][1], gen
        if best_fit == perfect:
            break
        # Elitism + tournament selection + mutation/crossover.
        survivors = [t for _, t in scored[: max(2, pop_size // 5)]]
        pop = survivors[:]
        while len(pop) < pop_size:
            if rng.random() < 0.5:
                a, b = rng.choice(survivors), rng.choice(survivors)
                child = crossover(a, b, rng)
            else:
                child = mutate(rng.choice(survivors), rng, max_depth)
            pop.append(child)
    return best, best_fit, best_gen


# Common target truth tables (row order = MSB-first, matches evaluate()).
TARGETS = {
    "NOT": (1, [1, 0]),                 # 1 input
    "AND": (2, [0, 0, 0, 1]),
    "OR":  (2, [0, 1, 1, 1]),
    "XOR": (2, [0, 1, 1, 0]),
    "NAND": (2, [1, 1, 1, 0]),
}


if __name__ == "__main__":
    for name, (n, table) in TARGETS.items():
        term, fit_score, gen = evolve(table, n, generations=300, pop_size=300, seed=1)
        from ski_term import pretty
        tag = "solved" if fit_score == len(table) else "best"
        print(f"{name:5s}  {tag} {fit_score}/{len(table)} @gen {gen}:  {pretty(term)}")

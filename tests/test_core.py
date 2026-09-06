import os
from collections import Counter

import pytest

from lotto.feeds import parse_va_feed
from lotto.games import GAMES
from lotto.picker import PickRequest, batch, check_filters, generate
from lotto.rng import ChaChaRNG
from lotto.wheel import abbreviated_wheel, full_wheel
from lotto.health import health_report
from lotto.entropy.pool import combine
from lotto.entropy.base import SourceResult


def test_rng_uniform_no_modulo_bias():
    rng = ChaChaRNG(b"\x01" * 32)
    c = Counter(rng.below(7) for _ in range(140_000))
    for v in c.values():
        assert abs(v - 20_000) < 800


def test_rng_deterministic_for_same_seed():
    a = ChaChaRNG(b"\x02" * 32).sample_distinct(1, 69, 5)
    b = ChaChaRNG(b"\x02" * 32).sample_distinct(1, 69, 5)
    assert a == b


@pytest.mark.parametrize("key", list(GAMES))
def test_every_game_generates_valid_pick(key):
    g = GAMES[key]
    p = generate(PickRequest(key), os.urandom(32))
    main = g.main
    assert len(p.main) == (main.count if not main.user_sets_count else main.count)
    assert all(main.lo <= n <= main.hi for n in p.main)
    if main.distinct:
        assert len(set(p.main)) == len(p.main) and p.main == sorted(p.main)
    if g.bonus:
        assert g.bonus.lo <= p.bonus <= g.bonus.hi
    else:
        assert p.bonus is None


def test_locked_and_excluded():
    p = generate(PickRequest("cash5", strategy="lucky", lucky=[5, 9], locked=[9], exclude=[1, 2, 3]), os.urandom(32))
    assert 9 in p.main
    assert not {1, 2, 3} & set(p.main)


def test_slider_zero_returns_base():
    seed = os.urandom(32)
    p = generate(PickRequest("cash5", strategy="lucky", lucky=[3, 9, 14, 22, 31], entropy=0.0), seed)
    assert p.main == [3, 9, 14, 22, 31]


def test_phrase_repeatable_at_zero_entropy():
    a = generate(PickRequest("cash5", strategy="phrase", phrase="hello", entropy=0), os.urandom(32)).main
    b = generate(PickRequest("cash5", strategy="phrase", phrase="hello", entropy=0), os.urandom(32)).main
    assert a == b


def test_filters_reject_patterns():
    g = GAMES["powerball"]
    assert check_filters(g, [1, 2, 3, 4, 5], 1, ["anti_pattern"], None) is not None
    assert check_filters(g, [3, 7, 11, 22, 30], 1, ["anti_split"], None) is not None
    assert check_filters(g, [3, 7, 41, 52, 66], 1, ["anti_split", "anti_pattern"], None) is None


def test_batch_limits_shared_numbers():
    picks = batch(PickRequest("megamillions"), os.urandom(32), 6, max_shared=1)
    for i, a in enumerate(picks):
        for b in picks[i + 1:]:
            assert len(set(a.main) & set(b.main)) <= 1


def test_parse_va_feed_formats():
    pb = parse_va_feed(GAMES["powerball"], "Results for Powerball\n9/5/2026; 15,40,47,53,59; Powerball: 9\n")
    assert pb[0].main == [15, 40, 47, 53, 59] and pb[0].bonus == 9 and pb[0].date == "2026-09-05"
    p3 = parse_va_feed(GAMES["pick3"], "Results for Pick 3\n9/5/2026; Day: 8,1,7; Fireball: 5; Night: 9,3,7; Fireball: 2\n5/22/1989; Night: 9,1,4\n")
    assert [(d.session, d.main, d.fireball) for d in p3] == [("day", [8, 1, 7], 5), ("night", [9, 3, 7], 2), ("night", [9, 1, 4], None)]
    c5 = parse_va_feed(GAMES["cash5"], "Results for Cash 5\n9/5/2026; 1,24,26,40,42\n2/5/1993; Night: 15,18,27,31,32\n")
    assert c5[0].main == [1, 24, 26, 40, 42] and c5[1].session == "night"
    cp = parse_va_feed(GAMES["cashpop"], "Results for Cash Pop\nSun 09/06/2026 - 12:00 PM; 1; Lunch Break\n")
    assert cp[0].main == [1] and cp[0].session == "Lunch Break"


def test_wheels():
    assert len(full_wheel("cash5", [1, 2, 3, 4, 5, 6])) == 6
    ab = abbreviated_wheel("cash5", [3, 9, 14, 22, 31, 40, 45, 12], guarantee=3, seed=b"\x03" * 32)
    from itertools import combinations
    for trio in combinations([3, 9, 14, 22, 31, 40, 45, 12], 3):
        assert any(set(trio) <= set(t) for t in ab)


def test_health_scores_cpu_high():
    assert health_report(os.urandom(8192))["score"] >= 85


def test_combine_changes_with_any_source():
    a = SourceResult("cpu", True, 32, b"a" * 32)
    b = SourceResult("cpu", True, 32, b"b" * 32)
    assert combine([a]) != combine([b])

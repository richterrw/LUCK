from luck.selection import OptionQuote, pick_closest_delta


def _calls():
    return [
        OptionQuote("C140", 140, delta=0.78, bid=11.0, ask=11.4),
        OptionQuote("C150", 150, delta=0.52, bid=4.0, ask=4.3),
        OptionQuote("C160", 160, delta=0.27, bid=1.1, ask=1.3),
    ]


def _puts():
    return [
        OptionQuote("P140", 140, delta=-0.22, bid=1.0, ask=1.2),
        OptionQuote("P150", 150, delta=-0.48, bid=3.9, ask=4.2),
        OptionQuote("P160", 160, delta=-0.74, bid=10.5, ask=11.0),
    ]


def test_picks_atm_call_for_half_delta():
    chosen = pick_closest_delta(_calls(), target_delta=0.50)
    assert chosen.symbol == "C150"


def test_picks_atm_put_for_half_delta_uses_magnitude():
    chosen = pick_closest_delta(_puts(), target_delta=0.50)
    assert chosen.symbol == "P150"


def test_targets_otm_delta():
    chosen = pick_closest_delta(_calls(), target_delta=0.25)
    assert chosen.symbol == "C160"


def test_skips_untradable_no_ask():
    quotes = [
        OptionQuote("C150", 150, delta=0.50, bid=0.0, ask=0.0),  # no quote
        OptionQuote("C160", 160, delta=0.30, bid=1.1, ask=1.3),
    ]
    chosen = pick_closest_delta(quotes, target_delta=0.50)
    assert chosen.symbol == "C160"  # the only tradable one


def test_returns_none_when_nothing_tradable():
    quotes = [OptionQuote("C150", 150, delta=0.50, bid=0.0, ask=0.0)]
    assert pick_closest_delta(quotes, target_delta=0.50) is None

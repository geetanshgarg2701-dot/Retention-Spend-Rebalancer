import pytest

from src.checker import OVERCLAIMS, SPELLED, allowed_numbers, allowed_sets, check_text

FACTS = {
    "repeat_rate": 0.334,
    "customers": 1378,
    "orders": 2402,
    "median_days": 53.06,
    "payback_month": 1,
    "revenue": 129793.09,
    "funnel": [{"label": "2 or more orders", "customers": 460}],
    "range": {"first_month": "2024-01", "last_month": "2025-12"},
    "horizon_months": 12,
    "weight": -5,
}


def ok(text, **kw):
    return check_text(text, FACTS, **kw)


# ---------------------------------------------------------------- allowed numbers

def test_numbers_are_allowed_in_every_rounding_and_as_percents():
    allowed = allowed_numbers(FACTS)
    for good in ("1378", "2402", "53", "53.1", "53.06", "129793", "129793.1", "129793.09", "33", "33.4", "460", "12", "5", "2024", "2025"):
        assert good in allowed, good
    # 33.4 percent rounds to 33, so 34 was never computed. The raw ratio 0.334 is a fact exactly as given, so it is allowed.
    assert "0.334" in allowed
    for bad in ("34", "1379", "54", "334", "13"):
        assert bad not in allowed, bad


def test_booleans_and_none_add_nothing():
    assert allowed_numbers({"a": True, "b": None}) == set()


# ------------------------------------------------------------------ good text

@pytest.mark.parametrize("text", [
    "About 33.4% of 1,378 customers ordered again.",
    "33% ordered again, and the median gap was 53 days.",
    "Revenue was 129,793.09 over 2,402 orders.",
    "Payback came in month 1 over 12 months.",
    "From 2024-01 to 2025-12 there were 460 customers with 2 or more orders.",
    "One channel looks stronger, and the figure 33.40% is the same as 33.4%.",
    "The loss of 5 stands out.",  # sign is ignored, only the figure is checked
])
def test_text_using_only_known_figures_passes(text):
    result = ok(text)
    assert result.ok, result.reason()


# ------------------------------------------------------------------- bad text

@pytest.mark.parametrize("text, bad", [
    ("34% ordered again.", ["34%"]),                       # 33.4 rounds to 33, so 34 was not computed
    ("There were 1,379 customers.", ["1,379"]),
    ("Revenue grew 18% last year.", ["18%"]),
    ("Customers ordered every 54 days.", ["54"]),
    ("That is 2.5 times as many.", ["2.5"]),
])
def test_figures_that_are_not_in_the_facts_are_flagged(text, bad):
    result = ok(text)
    assert not result.ok and result.bad_numbers == bad


def test_a_share_times_one_hundred_only_counts_when_written_as_a_percentage():
    facts = {"share_of_revenue": 0.3012, "customers": 405}
    assert check_text("Champions bring 30% of revenue.", facts).ok
    assert check_text("Champions bring 30 percent of revenue.", facts).ok
    # A plain 30 is not a fact. It only matches the percentage form of a share, so it must be refused.
    for text in ("Offer a discount within 30 days.", "Send 30 emails.", "Try a 30 dollar voucher."):
        result = check_text(text, facts)
        assert not result.ok and result.bad_numbers == ["30"], text


def test_percent_words_and_signs_are_both_checked_as_percentages():
    assert ok("33.4 percent of customers ordered again.").ok and ok("33.4 per cent of customers ordered again.").ok
    assert ok("34 percent of customers ordered again.").bad_numbers == ["34 percent"]
    assert ok("There were 33 customers.").bad_numbers == ["33"]  # 33 is a rounded share, not a plain fact


def test_a_fact_as_given_may_be_copied_exactly():
    assert ok("The raw ratio was 0.334 for repeat customers.").ok
    assert ok("The raw ratio was 0.335 for repeat customers.").bad_numbers == ["0.335"]


def test_allowed_sets_keep_plain_numbers_apart_from_percentages():
    plain, percent = allowed_sets({"share": 0.3012, "count": 405})
    assert "30" not in plain and "30" in percent and "30.12" in percent and "405" in plain and "405" in percent


def test_each_bad_figure_is_listed_once():
    assert ok("34% then 34% again and 77.").bad_numbers == ["34%", "77"]


@pytest.mark.parametrize("word", ["two", "three", "twelve", "half", "double", "twice", "hundred"])
def test_spelled_out_numbers_are_flagged(word):
    result = ok(f"About {word} of the customers came back.")
    assert not result.ok and result.spelled == [word]


def test_the_word_one_is_allowed():
    assert ok("One channel looks stronger than the other.").ok


@pytest.mark.parametrize("phrase", ["will increase", "guaranteed", "proven", "definitely"])
def test_overclaiming_language_is_flagged(phrase):
    result = ok(f"This {phrase} your revenue.")
    assert not result.ok and phrase in result.overclaims


def test_a_word_limit_is_enforced():
    long_text = "word " * 31
    assert ok(long_text, max_words=30).too_long and not ok(long_text, max_words=40).too_long


def test_reason_lists_every_problem():
    text = ok("It will increase by 99% and double.").reason()
    assert "99%" in text and "double" in text and "will increase" in text


def test_a_hostile_looking_number_does_not_crash_the_checker():
    assert not ok("1,2,3,4 and 9999999999999999999999 and 1e5").ok


def test_the_lists_are_lowercase_words():
    assert all(w == w.lower() and w.isalpha() for w in SPELLED) and all(p == p.lower() for p in OVERCLAIMS)

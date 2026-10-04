import pytest

from src.loading import LoadError, read_upload

GOOD = b"Email,Created at,Total\na@example.com,2025-01-01,10.00\n,2025-01-02,\n"


def test_reads_text_and_keeps_blank_cells_as_empty_strings():
    df = read_upload("orders.csv", GOOD)
    assert list(df.columns) == ["Email", "Created at", "Total"]
    assert df.iloc[1].tolist() == ["", "2025-01-02", ""]
    assert df["Total"].iloc[0] == "10.00"  # not turned into a float


def test_na_like_text_is_not_turned_into_missing_values():
    df = read_upload("orders.csv", b"id,note\nNA,null\n")
    assert df.iloc[0].tolist() == ["NA", "null"]


def test_handles_bom_semicolons_and_cp1252():
    assert list(read_upload("a.csv", b"\xef\xbb\xbfa;b\n1;2\n").columns) == ["a", "b"]
    df = read_upload("a.csv", "name,total\ncafé,5\n".encode("cp1252"))
    assert df["name"].iloc[0] == "café"


@pytest.mark.parametrize(
    "name, data, kwargs, message",
    [
        ("orders.xlsx", GOOD, {}, "not a CSV"),
        ("orders.csv", b"", {}, "empty"),
        ("orders.csv", b"  \n\n", {}, "empty"),
        ("orders.csv", b"a,b,c\n", {}, "no orders"),
        ("orders.csv", GOOD, {"max_mb": 0}, "limit is 0 MB"),
        ("orders.csv", b"a,b\n1,2\n3,4\n5,6\n", {"max_rows": 2}, "more than 2 rows"),
        ("orders.csv", b'a,b\n1,2\n3,4,5,6\n', {}, "could not be read"),
        ("orders.csv", b"a,a ,b\n1,2,3\n", {}, "more than once"),
    ],
)
def test_bad_files_get_plain_messages(name, data, kwargs, message):
    with pytest.raises(LoadError, match=message):
        read_upload(name, data, **kwargs)


def test_the_default_row_cap_is_two_hundred_thousand_and_is_enforced():
    from src.loading import MAX_ROWS

    assert MAX_ROWS == 200_000
    just_over = b"a,b\n" + b"1,2\n" * (MAX_ROWS + 1)
    with pytest.raises(LoadError, match="more than 200,000 rows"):
        read_upload("big.csv", just_over)
    exactly = b"a,b\n" + b"1,2\n" * MAX_ROWS
    assert len(read_upload("ok.csv", exactly)) == MAX_ROWS

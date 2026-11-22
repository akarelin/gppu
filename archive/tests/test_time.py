# .. archived 2026-11-22: what gppu's reduction removed from tests/test_time.py, as it was last


# .. from fec31bb
class TestNowStr:
    def test_format(self):
        result = now_str()
        assert re.match(r"\d{8}\.\d{6}", result)


# .. from fec31bb
class TestPrettyTimedelta:
    def test_seconds_only(self):
        ts = now_ts() - 30
        result = pretty_timedelta(ts)
        assert "s" in result
        assert "m" not in result

    def test_minutes(self):
        ts = now_ts() - 120
        result = pretty_timedelta(ts)
        assert "m" in result

    def test_hours(self):
        ts = now_ts() - 7200
        result = pretty_timedelta(ts)
        assert "h" in result

    def test_days(self):
        ts = now_ts() - 172800
        result = pretty_timedelta(ts)
        assert "d" in result


# .. from fec31bb
class TestPrependDatestamp:
    def test_prepends_datestamp(self):
        result = prepend_datestamp("/tmp/file.txt")
        name = result.name
        assert re.match(r"\d{6} file\.txt", name)

    def test_custom_separator(self):
        result = prepend_datestamp("/tmp/file.txt", separator="_")
        name = result.name
        assert re.match(r"\d{6}_file\.txt", name)

    def test_preserves_directory(self):
        result = prepend_datestamp("/some/dir/file.txt")
        assert result.parent.parts[-2:] == ("some", "dir")


# .. from fec31bb
class TestAppendTimestamp:
    def test_appends_timestamp(self):
        result = append_timestamp("/tmp/backup.tar.gz")
        name = result.name
        assert "backup" in name
        assert re.search(r"\d{6}-\d{4}", name)

    def test_preserves_extension(self):
        result = append_timestamp("/tmp/data.csv")
        assert result.suffix == ".csv"

    def test_preserves_directory(self):
        result = append_timestamp("/some/dir/file.txt")
        assert result.parent.parts[-2:] == ("some", "dir")

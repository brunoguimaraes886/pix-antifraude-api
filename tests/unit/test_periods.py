from datetime import datetime, timedelta, timezone

from utils.periods import DAY, NIGHT, current_period, local_day_start, previous_period

SAO_PAULO = timezone(timedelta(hours=-3))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SAO_PAULO)


class TestCurrentPeriod:
    def test_morning_is_day(self):
        period = current_period(at(17, 10))

        assert period.kind == DAY
        assert period.start == at(17, 6)
        assert period.end == at(17, 22)

    def test_late_evening_is_night_until_next_morning(self):
        period = current_period(at(17, 23, 30))

        assert period.kind == NIGHT
        assert period.start == at(17, 22)
        assert period.end == at(18, 6)

    def test_dawn_belongs_to_the_night_that_started_yesterday(self):
        period = current_period(at(18, 3))

        assert period.kind == NIGHT
        assert period.start == at(17, 22)
        assert period.end == at(18, 6)

    def test_boundaries(self):
        assert current_period(at(17, 6)).kind == DAY
        assert current_period(at(17, 5, 59)).kind == NIGHT
        assert current_period(at(17, 21, 59)).kind == DAY
        assert current_period(at(17, 22)).kind == NIGHT

    def test_uses_the_timezone_of_the_transaction(self):
        """00:30 em UTC é 21:30 em São Paulo: o mesmo instante, períodos diferentes."""
        utc_moment = datetime(2026, 10, 18, 0, 30, tzinfo=timezone.utc)

        assert current_period(utc_moment).kind == NIGHT
        assert current_period(utc_moment.astimezone(SAO_PAULO)).kind == DAY


class TestPreviousPeriod:
    def test_before_a_day_comes_the_night(self):
        previous = previous_period(current_period(at(17, 10)))

        assert previous.kind == NIGHT
        assert previous.start == at(16, 22)
        assert previous.end == at(17, 6)

    def test_before_a_night_comes_the_day(self):
        previous = previous_period(current_period(at(18, 3)))

        assert previous.kind == DAY
        assert previous.start == at(17, 6)
        assert previous.end == at(17, 22)


def test_local_day_start():
    assert local_day_start(at(17, 23, 30)) == at(17, 0)

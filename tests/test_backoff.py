from contextlib import nullcontext as does_not_raise
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from resilient_circuit.backoff import ExponentialDelay, FixedDelay


class TestExponentialDelay:
    # noinspection PyDataclass
    def test_should_be_immutable(self):
        # given
        backoff = ExponentialDelay(min_delay=timedelta(0), max_delay=timedelta(10))

        # when / then
        with pytest.raises(FrozenInstanceError):
            backoff.min_delay = timedelta(10)

    def test_should_construct_backoff_with_defaults(self):
        # when
        backoff = ExponentialDelay(
            min_delay=timedelta(seconds=0), max_delay=timedelta(seconds=10)
        )

        # then
        assert backoff.min_delay.total_seconds() == 0
        assert backoff.max_delay.total_seconds() == 10
        assert backoff.factor == 2
        assert backoff.jitter is None

    def test_should_require_positive_attempt(self):
        # given
        backoff = ExponentialDelay(min_delay=timedelta(0), max_delay=timedelta(10))

        # when / then
        with pytest.raises(ValueError, match="`attempt` must be positive."):
            backoff.for_attempt(0)

    @pytest.mark.parametrize(
        ["expectation", "jitter"],
        [
            pytest.param(does_not_raise(), None, id="not-set"),
            pytest.param(does_not_raise(), 0.5, id="in-range-.5"),
            pytest.param(does_not_raise(), 0.9, id="in-range-.9"),
            pytest.param(does_not_raise(), 0.1, id="in-range-.1"),
            pytest.param(does_not_raise(), 0, id="in-range-outermost-lhs"),
            pytest.param(does_not_raise(), 1, id="in-range-outermost-rhs"),
            pytest.param(pytest.raises(ValueError), -0.1, id="outside-range-negative"),
            pytest.param(pytest.raises(ValueError), 1.1, id="outside-range-positive"),
        ],
    )
    def test_should_require_jitter_to_be_in_closed_0_1_range(self, expectation, jitter):
        # when / then
        with expectation:
            ExponentialDelay(min_delay=timedelta(0), max_delay=timedelta(1), jitter=jitter)

    @pytest.mark.parametrize(
        ["attempt", "expected"],
        [
            pytest.param(1, 0.05),
            pytest.param(2, 0.1),
            pytest.param(3, 0.2),
            pytest.param(4, 0.4),
            pytest.param(10, 25.6),
        ],
    )
    def test_should_calculate_delay_for_attempt(self, attempt, expected):
        # given
        backoff = ExponentialDelay(
            min_delay=timedelta(milliseconds=50),
            max_delay=timedelta(seconds=100),
        )

        # when
        delay = backoff.for_attempt(attempt)

        # then
        assert delay == expected

    @pytest.mark.parametrize("attempt", range(1, 10))
    def test_should_not_exceed_max_delay(self, attempt):
        # given
        max_delay = 0.1
        backoff = ExponentialDelay(
            min_delay=timedelta(milliseconds=60),
            max_delay=timedelta(seconds=max_delay),
        )

        # when
        # noinspection PyTypeChecker
        delay = backoff.for_attempt(attempt)

        # then
        assert delay <= max_delay

    @pytest.mark.parametrize("_", range(10))
    def test_should_apply_jitter_to_the_delay(self, _):
        # given
        backoff = ExponentialDelay(
            min_delay=timedelta(milliseconds=50),
            max_delay=timedelta(seconds=100),
            jitter=0.1,
        )

        # when
        delay = backoff.for_attempt(5)

        # then
        assert 0.72 < delay < 0.88


class TestFixedDelay:
    def test_should_require_positive_attempt(self):
        # given
        delay = FixedDelay(timedelta(seconds=1))

        # when / then
        with pytest.raises(ValueError, match="`attempt` must be positive."):
            delay.for_attempt(0)

    @pytest.mark.parametrize("attempt", range(1, 5))
    def test_should_provide_equal_delays(self, attempt):
        # given
        delay = FixedDelay(timedelta(seconds=1))

        # when
        # noinspection PyTypeChecker
        delay_for_attempt = delay.for_attempt(attempt)

        # then
        assert delay_for_attempt == 1

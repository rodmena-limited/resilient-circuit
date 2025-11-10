from datetime import timedelta
from unittest.mock import Mock, call

import pytest

from highway_circutbreaker import retry as retry_module
from highway_circutbreaker.backoff import Delay
from highway_circutbreaker.exceptions import RetriesExceeded
from highway_circutbreaker.retry import RetryPolicy


class TestRetryPolicy:
    def test_should_return_result_when_execution_successful(self):
        # given
        method = Mock(return_value="test")
        retry = RetryPolicy()

        # when
        result = retry(method)()

        # then
        assert result == "test"

    def test_should_retry_when_first_execution_fails(self):
        # given
        method = Mock(side_effect=[RuntimeError, "test"])
        retry = RetryPolicy()

        # when
        result = retry(method)()

        # then
        assert result == "test"
        assert method.call_count == 2

    def test_should_not_retry_beyond_max_retries(self):
        # given
        method = Mock(side_effect=RuntimeError)
        retry = RetryPolicy(max_retries=2)

        # when / then
        with pytest.raises(RetriesExceeded):
            retry(method)()

        assert method.call_count == 3

    def test_should_retry_with_delays_between_calls(self, mocker):
        # given
        mocked_sleep = mocker.patch.object(retry_module, "sleep")
        retry = RetryPolicy(backoff=Delay(timedelta(seconds=1)))
        method = Mock(side_effect=[RuntimeError, RuntimeError, "test"])

        # when
        retry(method)()

        # then
        mocked_sleep.assert_has_calls([call(1.0), call(1.0)])

    def test_should_retry_when_exception_must_be_handled(self):
        # given
        retry = RetryPolicy(max_retries=3, handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=[RuntimeError, RuntimeError, "test"])

        # when
        result = retry(method)()

        # then
        assert result == "test"
        assert method.call_count == 3

    def test_should_abort_when_exception_must_not_be_handled(self):
        # given
        retry = RetryPolicy(max_retries=3, handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=ValueError)

        # when / then
        with pytest.raises(ValueError):
            retry(method)()

        assert method.call_count == 1

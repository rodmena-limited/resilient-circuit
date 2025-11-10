from fractions import Fraction

import pytest

from highway_circutbreaker.buffer import BinaryCircularBuffer, GenericCircularBuffer


class TestGenericCircularBuffer:
    def test_should_require_positive_size(self):
        # when / then
        with pytest.raises(ValueError, match="`size` must be positive."):
            GenericCircularBuffer[int](0)

    def test_should_provide_valid_len(self):
        # given
        buffer = GenericCircularBuffer[int](100)

        # when
        buffer.add(1)

        # then
        assert len(buffer) == 1

    def test_should_provide_valid_repr(self):
        # given
        buffer = GenericCircularBuffer[int](2)
        buffer.add(2)
        buffer.add(5)

        # then
        assert repr(buffer) == "<GenericCircularBuffer(size=2): [2, 5]>"

    def test_should_not_exceed_its_size(self):
        # given
        buffer = GenericCircularBuffer[int](5)

        # when
        for i in range(10):
            buffer.add(i)

        # then
        assert len(buffer) == 5

    def test_should_be_full_when_size_reached(self):
        # given
        buffer = GenericCircularBuffer[int](2)

        # when
        buffer.add(1)
        buffer.add(2)

        # then
        assert buffer.is_full is True

    def test_should_not_be_full_when_size_not_reached(self):
        # given
        buffer = GenericCircularBuffer[int](2)

        # when
        buffer.add(1)

        # then
        assert buffer.is_full is False


class TestBinaryCircularBuffer:
    def test_should_count_successes_and_failures(self):
        # given
        buffer = BinaryCircularBuffer(5)

        # when
        buffer.add(True)
        buffer.add(False)
        buffer.add(True)
        buffer.add(True)
        buffer.add(False)

        # then
        assert buffer.success_count == 3
        assert buffer.failure_count == 2

    def test_should_calculate_valid_ratios(self):
        # given
        buffer = BinaryCircularBuffer(5)

        # when
        buffer.add(True)
        buffer.add(False)
        buffer.add(True)
        buffer.add(True)
        buffer.add(False)

        # then
        assert buffer.success_rate + buffer.failure_rate == 1.0

        assert buffer.success_rate == Fraction(3, 5)
        assert buffer.failure_rate == Fraction(2, 5)

import pytest
from math_utils import multiply

def test_multiply_positive_numbers():
    assert multiply(2, 3) == 6

def test_multiply_negative_numbers():
    assert multiply(-2, -3) == 6

def test_multiply_positive_and_negative_number():
    assert multiply(2, -3) == -6

def test_multiply_zero():
    assert multiply(0, 5) == 0
    assert multiply(5, 0) == 0

def test_multiply_one():
    assert multiply(1, 5) == 5
    assert multiply(5, 1) == 5

# tests/test_multi_step_probe.py

import unittest
from multi_step_probe import normalize_name

class TestMultiStepProbe(unittest.TestCase):

    def test_normalize_name(self):
        self.assertEqual(normalize_name('  John   Doe  '), 'John Doe')
        self.assertEqual(normalize_name('Alice'), 'Alice')
        self.assertEqual(normalize_name('   Bob   '), 'Bob')
        self.assertEqual(normalize_name(''), '')
        self.assertEqual(normalize_name('   '), '')
        self.assertEqual(normalize_name('  multiple    spaces '), 'multiple spaces')
        self.assertEqual(normalize_name('singleword'), 'singleword')
        self.assertEqual(normalize_name('  leading and trailing '), 'leading and trailing')
        self.assertEqual(normalize_name('  mixed   CASE   '), 'mixed CASE')
        self.assertEqual(normalize_name('  numbers 123 456 '), 'numbers 123 456')

if __name__ == '__main__':
    unittest.main()

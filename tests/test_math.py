import unittest
from decimal import Decimal, ROUND_HALF_UP

class BenchmarkMathTests(unittest.TestCase):
    def test_retailer_tax(self):
        taxable = 150 * 5000  # paise
        tax = int((Decimal(taxable) * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        cgst = tax // 2
        sgst = tax - cgst
        self.assertEqual((taxable, cgst, sgst, taxable + tax), (750000, 18750, 18750, 787500))

    def test_stock_balances(self):
        self.assertEqual(100 + 60 - 40, 120)
        self.assertEqual(30 - Decimal('10.5'), Decimal('19.5'))
        self.assertEqual(5 - Decimal('1.2'), Decimal('3.8'))
        self.assertEqual(500 - 188 - 6, 306)
        self.assertEqual(30 - 9, 21)
        self.assertEqual(50 + 188 - 150, 88)

    def test_variances(self):
        self.assertEqual((188 - 200) / 200 * 100, -6.0)
        self.assertEqual((10.5 - 10) / 10 * 100, 5.0)

    def test_outstanding(self):
        self.assertEqual(787500 - 400000, 387500)

if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import Mock

from instrument_worker import MeasurementWorker


class MeasurementTests(unittest.TestCase):
    def run_response(self, response):
        instrument = Mock()
        instrument.query.return_value = response
        worker = MeasurementWorker(instrument, interval_ms=0, max_points=1, infinite=False)
        values, errors = [], []
        worker.data_received.connect(lambda value, unit: values.append(value))
        worker.error_occurred.connect(errors.append)
        worker.run()
        return values, errors

    def test_scientific_reading_with_surrounding_newlines(self):
        values, errors = self.run_response("\r\n+1.23450000E+01\r\n")
        self.assertEqual(values, [12.345])
        self.assertEqual(errors, [])

    def test_blank_response_is_reported_without_recording_a_value(self):
        values, errors = self.run_response("\r\n")
        self.assertEqual(values, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("пустой ответ", errors[0])
        self.assertIn(r"\r\n", errors[0])

    def test_invalid_response_is_not_silently_discarded(self):
        values, errors = self.run_response("ERROR")
        self.assertEqual(values, [])
        self.assertIn("'ERROR'", errors[0])


if __name__ == "__main__":
    unittest.main()

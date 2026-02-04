# -*- coding: utf-8 -*-
import csv
import logging
from io import StringIO
from datetime import datetime

_logger = logging.getLogger(__name__)


class FileGenerator:
    """Service class for generating flat files (CSV, pipe-delimited, etc.)"""

    def __init__(self, delimiter=',', encoding='utf-8', include_header=True):
        """
        Initialize file generator

        :param delimiter: Field delimiter (default: ,)
        :param encoding: File encoding (default: utf-8)
        :param include_header: Include header row (default: True)
        """
        self.delimiter = delimiter
        self.encoding = encoding
        self.include_header = include_header

    def generate_csv(self, headers, data_rows):
        """
        Generate CSV/delimited file content

        :param headers: List of header names
        :param data_rows: List of lists/tuples containing row data
        :return: File content as string
        """
        try:
            output = StringIO()
            writer = csv.writer(
                output,
                delimiter=self.delimiter,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator='\n'
            )

            # Write header
            if self.include_header:
                writer.writerow(headers)

            # Write data rows
            for row in data_rows:
                # Convert all values to strings, handle None
                clean_row = [self._clean_value(val) for val in row]
                writer.writerow(clean_row)

            content = output.getvalue()
            output.close()

            _logger.info(f"Generated file with {len(data_rows)} rows")
            return content

        except Exception as e:
            _logger.error(f"Error generating file: {str(e)}")
            raise

    def generate_from_records(self, headers, records, field_mapping):
        """
        Generate file from Odoo recordset using field mapping

        :param headers: List of header names for the output file
        :param records: Odoo recordset
        :param field_mapping: Dict mapping header names to field names/callables
                             Example: {'ProductID': 'id', 'Name': lambda r: r.name.upper()}
        :return: File content as string
        """
        try:
            data_rows = []

            for record in records:
                row = []
                for header in headers:
                    field = field_mapping.get(header)

                    if field is None:
                        # No mapping, use empty value
                        value = ''
                    elif callable(field):
                        # Field is a function/lambda
                        value = field(record)
                    elif '.' in str(field):
                        # Handle related fields (e.g., 'partner_id.name')
                        value = self._get_related_field_value(record, field)
                    else:
                        # Direct field access
                        value = getattr(record, field, '')

                    row.append(value)

                data_rows.append(row)

            return self.generate_csv(headers, data_rows)

        except Exception as e:
            _logger.error(f"Error generating file from records: {str(e)}")
            raise

    def _get_related_field_value(self, record, field_path):
        """
        Get value from related field using dot notation

        :param record: Odoo record
        :param field_path: Field path (e.g., 'partner_id.name')
        :return: Field value or empty string
        """
        try:
            value = record
            for field in field_path.split('.'):
                value = getattr(value, field, '')
                if not value:
                    return ''
            return value
        except Exception:
            return ''

    def _clean_value(self, value):
        """
        Clean and format value for CSV output

        :param value: Raw value
        :return: Cleaned string value
        """
        if value is None or value == False:
            return ''

        # Handle datetime
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')

        # Handle float
        if isinstance(value, float):
            return f"{value:.2f}"

        # Handle boolean
        if isinstance(value, bool):
            return '1' if value else '0'

        # Convert to string and strip whitespace
        return str(value).strip()

    @staticmethod
    def generate_filename(prefix, timestamp=None, extension='csv'):
        """
        Generate a standardized filename

        :param prefix: File prefix (e.g., 'products', 'orders')
        :param timestamp: Datetime object (defaults to now)
        :param extension: File extension (default: csv)
        :return: Filename string
        """
        if timestamp is None:
            timestamp = datetime.now()

        timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S')
        return f"{prefix}_{timestamp_str}.{extension}"

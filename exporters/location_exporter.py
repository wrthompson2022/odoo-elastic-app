# -*- coding: utf-8 -*-
"""
Location Exporter for Elastic Integration

Exports ship-to address data to the Elastic platform via SFTP.
File format: locations.csv

One row per customer + delivery address combination:
* The customer's primary address is emitted with ShipToID="SAME".
* Each child contact of type "delivery" is emitted with its own ShipToID
  (legacy_account_number when present, otherwise the contact ID).
"""
import logging

from .base_exporter import BaseExporter
from ..services.file_generator import FileGenerator

_logger = logging.getLogger(__name__)


class LocationExporter(BaseExporter):
    """
    Exports customer ship-to locations (res.partner) data to Elastic.

    Output file format matches: locations.csv
    Headers: SoldToID,ShipToID,ShipToName,Address1,Address2,Address3,City,
             State,PostalCode,Country
    """

    def get_export_type(self):
        return 'location'

    def get_model_name(self):
        return 'res.partner'

    def get_file_prefix(self):
        return 'locations'

    def get_export_domain(self):
        domain = [
            ('is_company', '=', True),
            ('customer_rank', '>', 0),
        ]
        if self.config.export_only_synced_customers:
            domain.append(('elastic_sync_enabled', '=', True))
        return domain

    def get_export_headers(self):
        return [
            'SoldToID',
            'ShipToID',
            'ShipToName',
            'Address1',
            'Address2',
            'Address3',
            'City',
            'State',
            'PostalCode',
            'Country',
        ]

    def get_field_mapping(self):
        # The location exporter has its own export() method.
        return {}

    @staticmethod
    def _row_for_partner(sold_to_id, ship_to_id, partner):
        return [
            sold_to_id,
            ship_to_id,
            partner.name or '',
            partner.street or '',
            partner.street2 or '',
            '',  # Address3 not used in Odoo
            partner.city or '',
            partner.state_id.code if partner.state_id else '',
            partner.zip or '',
            partner.country_id.name if partner.country_id else '',
        ]

    def _ship_to_id_for(self, contact):
        if contact.legacy_account_number:
            return contact.legacy_account_number
        return str(contact.id)

    def export(self):
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info('Starting %s export...', export_type)
            customers = self.env[model_name].search(self.get_export_domain())

            if not customers:
                message = f'No {export_type} records found to export'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}

            self.pre_export_hook(customers)

            data_rows = []
            for customer in customers:
                sold_to_id = customer._get_sold_to_id()

                # Primary address — emitted with ShipToID="SAME".
                data_rows.append(self._row_for_partner(sold_to_id, 'SAME', customer))

                # Each delivery child contact gets its own ShipToID.
                delivery_contacts = customer.child_ids.filtered(
                    lambda c: c.type == 'delivery'
                )
                for contact in delivery_contacts:
                    ship_to_id = self._ship_to_id_for(contact)
                    data_rows.append(self._row_for_partner(sold_to_id, ship_to_id, contact))

            file_content = self.file_generator.generate_csv(self.get_export_headers(), data_rows)
            filename = FileGenerator.generate_filename(prefix=self.get_file_prefix(), extension='csv')

            success, upload_message = self.sftp_service.upload_file(
                local_file_content=file_content,
                remote_filename=filename,
                remote_directory=self.config.sftp_export_path,
            )

            if not success:
                error_message = f'Failed to upload {export_type} file: {upload_message}'
                _logger.error(error_message)
                self.post_export_hook(customers, False, error_message)
                self.env['elastic.export.log'].create({
                    'export_type': export_type,
                    'model_name': model_name,
                    'record_count': len(data_rows),
                    'state': 'failed',
                    'message': error_message,
                })
                return {'success': False, 'message': error_message, 'record_count': len(data_rows)}

            success_message = (
                f'Successfully exported {len(data_rows)} {export_type} record(s) to {filename}'
            )
            _logger.info(success_message)
            self.post_export_hook(customers, True, success_message)

            log = self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': len(data_rows),
                'filename': filename,
                'state': 'success',
                'message': success_message,
            })

            return {
                'success': True,
                'message': success_message,
                'record_count': len(data_rows),
                'filename': filename,
                'log_id': log.id,
            }

        except Exception as e:
            error_message = f'{export_type} export failed: {e}'
            _logger.error(error_message, exc_info=True)
            self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': 0,
                'state': 'failed',
                'message': error_message,
            })
            return {'success': False, 'message': error_message, 'record_count': 0}

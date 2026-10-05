import base64
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestIncomeRegisterReport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Payslip = self.env["hr.payslip"]
        self.PayslipRun = self.env["hr.payslip.run"]
        self.Employee = self.env["hr.employee"]
        self.Company = self.env["res.company"]
        self.Contract = self.env["hr.contract"]

        self.company = self.env.company
        self.company.company_registry = "1234567-8"
        self.company.l10n_fi_payroll_ir_contact_person_id = (
            self.env["res.partner"]
            .create(
                {
                    "name": "Test Contact",
                    "phone": "+358401234567",
                    "email": "contact@example.com",
                }
            )
            .id
        )

        self.employee = self.Employee.create({"name": "Test Employee"})

        self.contract = self.Contract.create(
            {
                "name": "Test Contract",
                "employee_id": self.employee.id,
                "wage": 1000.0,
                "state": "open",
                "date_start": date(2025, 1, 1),
            }
        )

        self.payslip_run = self.PayslipRun.create(
            {
                "name": "Test Batch",
                "l10n_fi_payment_date": date(2025, 5, 25),
                "date_start": date(2025, 5, 1),
                "date_end": date(2025, 5, 31),
            }
        )

        self.payslip = self.Payslip.create(
            {
                "name": "Test Payslip",
                "number": "PS/2025/001",
                "employee_id": self.employee.id,
                "payslip_run_id": self.payslip_run.id,
                "date_from": date(2025, 5, 1),
                "date_to": date(2025, 5, 31),
                "contract_id": self.contract.id,
            }
        )

    def _create_employee(self, name):
        """Helper to create additional employees"""
        return self.Employee.create({"name": name})

    def _create_contract(self, employee):
        """Helper to create contracts"""
        return self.Contract.create(
            {
                "name": f"Contract for {employee.name}",
                "employee_id": employee.id,
                "wage": 1000.0,
                "state": "open",
                "date_start": date(2025, 1, 1),
            }
        )

    def _create_payslip(
        self, employee, date_from, date_to, payment_date, contract=None
    ):
        """Helper to create a payslip"""
        if contract is None:
            contract = self._create_contract(employee)

        return self.Payslip.create(
            {
                "name": f"Payslip for {employee.name}",
                "employee_id": employee.id,
                "date_from": date_from,
                "date_to": date_to,
                "payment_date": payment_date,
                "contract_id": contract.id,
            }
        )

    def test_payslip_action_incomes_register_report(self):
        """
        Test XML report generation and action return for a single payslip.
        """
        with patch(
            "odoo.addons.base.models.ir_ui_view.View._render_template"
        ) as mock_render:
            mock_render.return_value = "<root>Payslip XML</root>"

            self.payslip.payment_date = date(2025, 5, 25)
            action_result = self.payslip.action_incomes_register_report()

            self.assertTrue(self.payslip.l10n_fi_incomes_register_report)
            decoded_xml = base64.b64decode(
                self.payslip.l10n_fi_incomes_register_report
            ).decode("utf-8")
            self.assertEqual(decoded_xml, "<root>Payslip XML</root>")

            self.assertTrue(
                self.payslip.l10n_fi_incomes_register_report_filename.startswith(
                    "IR_Test_Employee_"
                )
            )
            self.assertTrue(
                self.payslip.l10n_fi_incomes_register_report_filename.endswith(".xml")
            )
            self.assertEqual(action_result["type"], "ir.actions.client")
            self.assertEqual(action_result["tag"], "reload")

    def test_run_action_incomes_register_report(self):
        """
        Test XML report generation for a batch, propagation to payslips,
        and action return.
        """
        with patch(
            "odoo.addons.base.models.ir_ui_view.View._render_template"
        ) as mock_render:
            mock_render.return_value = "<root>Batch XML</root>"

            action_result = self.payslip_run.action_incomes_register_report()

            self.assertTrue(self.payslip_run.l10n_fi_incomes_register_report)
            decoded_xml = base64.b64decode(
                self.payslip_run.l10n_fi_incomes_register_report
            ).decode("utf-8")
            self.assertEqual(decoded_xml, "<root>Batch XML</root>")
            self.assertTrue(
                self.payslip_run.l10n_fi_incomes_register_report_filename.startswith(
                    "IR_Test_Batch_"
                )
            )
            self.assertTrue(
                self.payslip_run.l10n_fi_incomes_register_report_filename.endswith(
                    ".xml"
                )
            )

            self.assertEqual(
                self.payslip.l10n_fi_incomes_register_report,
                self.payslip_run.l10n_fi_incomes_register_report,
            )
            self.assertEqual(
                self.payslip.l10n_fi_incomes_register_report_filename,
                self.payslip_run.l10n_fi_incomes_register_report_filename,
            )
            self.assertEqual(
                self.payslip.payment_date, self.payslip_run.l10n_fi_payment_date
            )

            self.assertEqual(action_result["type"], "ir.actions.act_window")
            self.assertEqual(action_result["res_model"], "hr.payslip.run")
            self.assertEqual(action_result["res_id"], self.payslip_run.id)

    def test_payslip_compute_ir_report_download(self):
        """
        Test the generation of the download link HTML for a single payslip.
        """
        self.payslip.l10n_fi_incomes_register_report = base64.b64encode(b"test")
        self.payslip.l10n_fi_incomes_register_report_filename = "test.xml"

        self.payslip._compute_ir_report_download()

        self.assertIn("href", str(self.payslip.l10n_fi_ir_report_download))
        self.assertIn("download", str(self.payslip.l10n_fi_ir_report_download))
        self.assertIn("test.xml", str(self.payslip.l10n_fi_ir_report_download))

    def test_run_compute_ir_report_download(self):
        """
        Test the generation of the download link HTML for a payslip run.
        """
        self.payslip_run.l10n_fi_incomes_register_report = base64.b64encode(
            b"test batch"
        )
        self.payslip_run.l10n_fi_incomes_register_report_filename = "test_batch.xml"

        self.payslip_run._compute_ir_report_download()

        self.assertIn("href", str(self.payslip_run.l10n_fi_ir_report_download))
        self.assertIn("download", str(self.payslip_run.l10n_fi_ir_report_download))
        self.assertIn(
            "test_batch.xml", str(self.payslip_run.l10n_fi_ir_report_download)
        )

    def test_create_xml_binary(self):
        """
        Test the _create_xml_binary helper method.
        """
        xml_string = " <root>Test</root> "
        expected_binary = base64.b64encode(b"<root>Test</root>")

        binary_content_payslip = self.payslip._create_xml_binary(xml_string)
        binary_content_run = self.payslip_run._create_xml_binary(xml_string)

        self.assertEqual(binary_content_payslip, expected_binary)
        self.assertEqual(binary_content_run, expected_binary)

    def test_multiple_payslips_identical_dates_success(self):
        """
        Test that multiple payslips with identical dates generate a single
        report successfully.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")
        employee3 = self._create_employee("Charlie Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip3 = self._create_payslip(
            employee3, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )

        payslips = payslip1 | payslip2 | payslip3

        with patch(
            "odoo.addons.base.models.ir_ui_view.View._render_template"
        ) as mock_render:
            mock_render.return_value = "<root>Combined Payslips XML</root>"

            payslips.action_incomes_register_report()

        self.assertTrue(payslip1.l10n_fi_incomes_register_report)
        self.assertEqual(
            payslip1.l10n_fi_incomes_register_report,
            payslip2.l10n_fi_incomes_register_report,
        )
        self.assertEqual(
            payslip1.l10n_fi_incomes_register_report,
            payslip3.l10n_fi_incomes_register_report,
        )

        self.assertEqual(
            payslip1.l10n_fi_incomes_register_report_filename,
            payslip2.l10n_fi_incomes_register_report_filename,
        )
        self.assertEqual(
            payslip1.l10n_fi_incomes_register_report_filename,
            payslip3.l10n_fi_incomes_register_report_filename,
        )

        self.assertIn("3_payslips", payslip1.l10n_fi_incomes_register_report_filename)

    def test_different_date_from_raises_error(self):
        """
        Test that payslips with different date_from raise UserError.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 7, 1), date(2025, 7, 31), date(2025, 7, 5)
        )

        payslips = payslip1 | payslip2

        with self.assertRaises(UserError) as context:
            payslips.action_incomes_register_report()

        error_msg = str(context.exception)
        self.assertIn("Period Start Date", error_msg)
        self.assertIn("2025-06-01", error_msg)
        self.assertIn("2025-07-01", error_msg)

    def test_different_date_to_raises_error(self):
        """
        Test that payslips with different date_to raise UserError.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 6, 1), date(2025, 7, 31), date(2025, 7, 5)
        )

        payslips = payslip1 | payslip2

        with self.assertRaises(UserError) as context:
            payslips.action_incomes_register_report()

        error_msg = str(context.exception)
        self.assertIn("Period End Date", error_msg)
        self.assertIn("2025-06-30", error_msg)
        self.assertIn("2025-07-31", error_msg)

    def test_different_payment_date_raises_error(self):
        """
        Test that payslips with different payment_date raise UserError.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 15)
        )

        payslips = payslip1 | payslip2

        with self.assertRaises(UserError) as context:
            payslips.action_incomes_register_report()

        error_msg = str(context.exception)
        self.assertIn("Payment Date", error_msg)
        self.assertIn("2025-07-05", error_msg)
        self.assertIn("2025-07-15", error_msg)

    def test_multiple_different_fields_all_mentioned(self):
        """
        Test that all differing fields are mentioned in error message.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 7, 1), date(2025, 7, 31), date(2025, 8, 5)
        )

        payslips = payslip1 | payslip2

        with self.assertRaises(UserError) as context:
            payslips.action_incomes_register_report()

        error_msg = str(context.exception)

        self.assertIn("Period Start Date", error_msg)
        self.assertIn("Period End Date", error_msg)
        self.assertIn("Payment Date", error_msg)

    def test_missing_payment_date_raises_error(self):
        """
        Test that payslips without payment_date raise UserError.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 6, 1), date(2025, 6, 30), None
        )

        payslips = payslip1 | payslip2

        with self.assertRaises(UserError) as context:
            payslips.action_incomes_register_report()

        error_msg = str(context.exception)
        self.assertIn("Payment date must be set", error_msg)
        self.assertIn("Bob Test", error_msg)

    def test_single_payslip_filename_uses_employee_name(self):
        """
        Test that single payslip uses employee name in filename.
        """
        employee = self._create_employee("John Doe")
        payslip = self._create_payslip(
            employee, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )

        with patch(
            "odoo.addons.base.models.ir_ui_view.View._render_template"
        ) as mock_render:
            mock_render.return_value = "<root>Single Payslip XML</root>"

            payslip.action_incomes_register_report()

        self.assertIn("John_Doe", payslip.l10n_fi_incomes_register_report_filename)
        self.assertTrue(
            payslip.l10n_fi_incomes_register_report_filename.startswith("IR_")
        )
        self.assertTrue(
            payslip.l10n_fi_incomes_register_report_filename.endswith(".xml")
        )

    def test_multiple_payslips_filename_uses_count_and_date(self):
        """
        Test that multiple payslips use count and date in filename.
        """
        employee1 = self._create_employee("Alice Test")
        employee2 = self._create_employee("Bob Test")

        payslip1 = self._create_payslip(
            employee1, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )
        payslip2 = self._create_payslip(
            employee2, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 5)
        )

        payslips = payslip1 | payslip2

        with patch(
            "odoo.addons.base.models.ir_ui_view.View._render_template"
        ) as mock_render:
            mock_render.return_value = "<root>Multiple Payslips XML</root>"

            payslips.action_incomes_register_report()

        filename = payslip1.l10n_fi_incomes_register_report_filename
        self.assertIn("2_payslips", filename)
        self.assertIn("20250601", filename)
        self.assertTrue(filename.startswith("IR_"))
        self.assertTrue(filename.endswith(".xml"))

    def _generate_payslip_xml(self, payslip):
        """Render the earnings payment report for one payslip.

        :param hr.payslip payslip: payslip to render
        :return: rendered XML
        :rtype: str
        """
        return payslip._generate_ir_report_xml(
            payslips=payslip,
            payment_date=payslip.payment_date,
            date_from=payslip.date_from,
            date_to=payslip.date_to,
        )

    def test_report_id_is_stable_and_source_matches_version(self):
        """ReportId stays within 40 characters and Source names Odoo 18.0."""
        self.payslip.payment_date = date(2025, 5, 25)
        first = etree.fromstring(str(self._generate_payslip_xml(self.payslip)))
        second = etree.fromstring(str(self._generate_payslip_xml(self.payslip)))
        report_id = first.findtext(".//ReportId")
        source = first.findtext(".//Source")
        self.assertTrue(report_id)
        self.assertLessEqual(len(report_id), 40)
        self.assertEqual(report_id, self.payslip.l10n_fi_ir_report_ref)
        self.assertEqual(second.findtext(".//ReportId"), report_id)
        self.assertTrue(source)
        self.assertLessEqual(len(source), 30)
        self.assertIn("18.0", source)

    def test_company_data_validation_lists_every_problem(self):
        """One error lists the business id and every missing contact field."""
        self.company.company_registry = False
        self.company.l10n_fi_payroll_ir_contact_person_id = self.env[
            "res.partner"
        ].create({"name": False})
        with self.assertRaises(UserError) as missing:
            self.payslip._validate_ir_company_data(self.company)
        message = str(missing.exception)
        self.assertIn("business ID", message)
        self.assertIn("no name", message)
        self.assertIn("phone", message)
        self.assertIn("email", message)

        self.company.l10n_fi_payroll_ir_contact_person_id = False
        with self.assertRaises(UserError) as no_contact:
            self.payslip._validate_ir_company_data(self.company)
        self.assertIn("contact person", str(no_contact.exception))

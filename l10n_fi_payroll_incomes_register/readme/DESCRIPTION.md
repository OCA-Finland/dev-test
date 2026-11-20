This module integrates the Finnish payroll localization (`l10n_fi_payroll_community`) with the
Incomes Register (Tulorekisteri) of the Finnish Tax Administration.

The payroll module produces the earnings payment report of each payslip as XML, which can be uploaded
manually in the Incomes Register's e-service. This module sends the same reports directly to the
Incomes Register's deferred Web Service, one payslip or many at a time, and shows the processing
result per payslip. The payroll workflow stays in Odoo and no manual upload is required.

Large payrolls are split into several deliveries and processed in the background.

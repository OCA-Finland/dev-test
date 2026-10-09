1. Prepare and confirm payslips as usual in *Payroll*. Only payslips in the *Done* state can be sent.
2. Send the reports:
   - from a payslip: click *Send to Incomes Register*;
   - from the payslip list: select payslips, then *Actions > Send to Incomes Register*;
   - from a payslip batch: click *Send to Incomes Register*.
3. Choose *Test* or *Production* (the wizard opens on *Test*). Review the preview
   (number of deliveries, warnings, sample XML, and any payslips skipped because they
   are not done) and confirm.
4. Follow the progress in *Payroll > Incomes Register > Submissions*. A payslip badge
   shows *Not sent*, *In progress*, *Valid*, or *Rejected*. The Incomes Register message
   is on the submission.
5. Rejected payslips can be corrected and sent again. A payslip whose report was accepted
   is locked: it cannot be reset to draft, cancelled, or deleted. A refund still runs and
   posts a warning.
6. Status is polled in the background. If a submission is *Uncertain* or *Needs check*,
   click *Check status*. A Payroll manager can then click *Mark as not received*; *Resend*
   keeps the same delivery id. The module never sends a report twice automatically.

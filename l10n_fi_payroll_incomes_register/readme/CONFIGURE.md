1. Make sure the Odoo server runs the job queue: add `queue_job` to `server_wide_modules` and
   configure the `queue_job` runner. Without it, reports stay queued.
2. Configure the payroll module: go to *Payroll > Configuration > Settings* and set the payroll
   defaults (pension insurance type, policy number and provider; accident insurance type, code and
   policy number) and the *Income Register Contact Person* with name, phone and email. Make sure the
   company has a Business ID. Import the occupation codes (TK10) with *Fetch from Register*.
3. Obtain an Incomes Register certificate from the Tax Administration's certificate service
   (testing or production certificates, API "Incomes Register").
4. Go to *Payroll > Configuration > Incomes Register Connections* and create a connection:
   - select the company and the environment (test or production). A company has one
     connection per environment;
   - the service address is filled in for that environment (test
     `https://ws-testi-2.tulorekisteri.fi/20170526`, production
     `https://ws.tulorekisteri.fi/20170526`);
   - upload the certificate and the private key (and the password if the file is protected);
   - optionally change the number of payslips per delivery (default 500).
5. Click *Test connection*. The connection becomes confirmed when the Incomes Register answers.

The module includes the Tax Administration CA packages that check the signature on
Incomes Register replies. A test connection uses IR Services Test Issuing CA v1
(valid until 20 February 2031). A production connection uses IR Services Issuing
CA v1 (valid until 28 October 2031). Both packages come from the certificate
service page "Certificate-specific CA packages" and are replaced by a module update.

Only Payroll managers can see and change connections and certificates. Payroll officers
can send reports and open submissions. You receive an activity 60 days before the
certificate expires; upload the renewed certificate on the same connection.

.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

===================
Agreement vismasign
===================
This module integrates the OCA ``agreement`` module with Visma Sign electronic
signatures.

The module allows sending agreements directly to Visma Sign, tracking
signature status automatically, and downloading signed PDF documents.

Features
========
* Create an agreement directly from a quotation (``agreement_sale``), either
  manually with a button or automatically on order confirmation
* Select the document template per agreement type, so lease agreements and
  the different sale agreement templates each use their own report
* Send agreements to Visma Sign directly from the agreement form
* Attach a local copy of the rendered (unsigned) document for audit purposes
* Store Visma Sign document, file, and invitation UUIDs on the agreement
* Automatic signature status synchronization using a scheduled action
* Download and attach the signed PDF document automatically
* Multi-company support

Configuration
=============

#. Go to
   *Agreements -> Settings* and configure:

   * **Auto-create Agreement on Order Confirmation**
     If enabled, confirming a quotation that has an agreement type set
     automatically creates the linked agreement. Otherwise, use the
     *Create Agreement* button on the quotation.

#. On each *Agreement Type* (*Agreements -> Configuration -> Agreement
   Types*), select the **Visma Sign Report** used to render the document
   for agreements of that type. Only agreement reports (e.g. provided by
   ``agreement_legal``) and sale order reports are offered. A sale order
   report is rendered from the quotation the agreement was created from.
   This is required before an agreement of that type can be sent for
   signature.

#. Ensure that a Visma Sign backend is configured for the company (requires
   the **Connector Manager** group (``connector.group_connector_manager``) —
   see ``connector_vismasign``'s README). Sending an agreement itself does
   not require this group, since ``action_vismasign_send()`` accesses the
   backend via ``sudo()``.

Usage
=====

#. On a quotation, set the **Agreement Type**, then either:

   * click *Create Agreement*, or
   * confirm the order, if automatic creation is enabled

   This creates an agreement linked to the quotation via ``agreement_id``.

#. Open the agreement (not a template).

#. Click:

   ::

       Send for Signature

#. The module will:

   * render the document using the report configured on the agreement's type
   * attach the rendered PDF to the agreement as an audit-trail copy
   * create a Visma Sign document
   * upload the PDF
   * send the signature invitation to the partner

#. Signature status is updated automatically every 15 minutes using a cron job.

#. Once the agreement has been signed:

   * the signed PDF is downloaded automatically
   * the signed document is attached to the agreement
   * a chatter notification is posted on the agreement

Technical Details
=================

Scheduled Action
----------------

The module installs the following scheduled action:

::

    Visma Sign: Update Invitation Status (Agreements)

Default interval:

* Every 15 minutes

Agreement Fields
-----------------

The following technical fields are added to the agreement:

* ``vismasign_document_uuid``
* ``vismasign_file_uuid``
* ``vismasign_invitation_uuid``
* ``vismasign_status``
* ``vismasign_last_check``

Agreement Type Fields
----------------------

* ``report_id``: report used to render agreements of this type. Required
  before an agreement of that type can be sent for signature. An agreement
  report is rendered for the agreement itself; a sale order report is
  rendered for the single quotation linked to the agreement.

Sale Order
----------

* ``action_create_agreement()``: creates the agreement for the quotation
  using its ``agreement_type_id`` (from ``agreement_sale``) and links it back
  via ``agreement_id``.
* Confirming an order auto-creates the agreement when the
  ``agreement_vismasign.auto_create_agreement_on_confirm`` system parameter
  is enabled.


Known issues / Roadmap
======================
\-

Credits
=======

Contributors
------------

* Valtteri Lattu <valtteri.lattu@futural.fi>

Maintainer
----------

.. image:: https://tawasta.fi/templates/tawastrap/images/logo.png
   :alt: Oy Tawasta OS Technologies Ltd.
   :target: https://tawasta.fi/

This module is maintained by Oy Tawasta OS Technologies Ltd.

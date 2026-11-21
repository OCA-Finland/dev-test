class PaymentLogEventType:
    INITIATION = 'initiation'
    CONFIRMATION = 'confirmation'
    STATUS_POLL = 'status_poll'

    SELECTION = [
        (INITIATION, 'Initiation'),
        (CONFIRMATION, 'Confirmation'),
        (STATUS_POLL, 'Status Poll'),
    ]
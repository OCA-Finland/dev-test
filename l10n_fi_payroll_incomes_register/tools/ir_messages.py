# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Read Incomes Register acknowledgement documents.

The parser uses local names so a prefix chosen by the service does not matter.
"""

from lxml import etree


def child(element, name):
    """Return the first direct child with this local name.

    :param lxml.etree._Element element: parent element, or ``None``
    :param str name: local name, without a namespace
    :return: the child, or ``None`` when it is missing
    :rtype: lxml.etree._Element or None
    """
    if element is None:
        return None
    for node in element:
        if etree.QName(node).localname == name:
            return node
    return None


def error_text(element):
    """Join ErrorInfo children into one message.

    :param lxml.etree._Element element: document or fragment to scan
    :return: one line per error, or an empty string
    :rtype: str
    """
    if element is None:
        return ""
    messages = []
    for node in element.iter():
        if etree.QName(node).localname != "ErrorInfo":
            continue
        code = child(node, "ErrorCode")
        text = child(node, "ErrorMessage")
        code_text = (code.text or "").strip() if code is not None else ""
        message_text = (text.text or "").strip() if text is not None else ""
        messages.append(f"{code_text}: {message_text}".strip(": "))
    return "\n".join(messages)


def _item_id(node):
    """Return the ItemId text of one status item.

    :param lxml.etree._Element node: Item element
    :return: item id, or an empty string
    :rtype: str
    """
    item_id = child(node, "ItemId")
    return (item_id.text or "").strip() if item_id is not None else ""


def ack_details(document):
    """Read the status, IR id, and errors from an AckFromIR document.

    :param lxml.etree._Element document: AckFromIR element, as its own root
    :return: ``status`` (int), ``ir_delivery_id`` (str or False), ``errors`` (str)
    :rtype: dict
    :raises ValueError: the document has no delivery status
    """
    ack = child(document, "AckData")
    status_node = child(ack, "DeliveryDataStatus")
    status_text = (status_node.text or "").strip() if status_node is not None else ""
    if not status_text:
        raise ValueError("AckFromIR has no DeliveryDataStatus")
    delivery = child(ack, "IRDeliveryId")
    ir_delivery_id = (delivery.text or "").strip() if delivery is not None else ""
    return {
        "status": int(status_text),
        "ir_delivery_id": ir_delivery_id or False,
        "errors": error_text(document),
    }


def status_details(document):
    """Read a GetDeliveryDataStatus answer.

    Item ids are the report references sent on the earnings report. Invalid
    items keep the error text that belongs to that item.

    :param lxml.etree._Element document: StatusResponseFromIR element
    :return: status, IR delivery id, errors, and invalid items
    :rtype: dict
    :raises ValueError: the document has no delivery status
    """
    response = child(document, "StatusResponse")
    status_node = child(response, "DeliveryDataStatus")
    status_text = (status_node.text or "").strip() if status_node is not None else ""
    if not status_text:
        raise ValueError("StatusResponse has no DeliveryDataStatus")
    delivery = child(response, "IRDeliveryId")
    ir_delivery_id = (delivery.text or "").strip() if delivery is not None else ""
    invalid_items = []
    invalid = child(response, "InvalidItems")
    nodes = invalid if invalid is not None else []
    for node in nodes:
        if etree.QName(node).localname != "Item":
            continue
        invalid_items.append({"item_id": _item_id(node), "errors": error_text(node)})
    parts = [
        error_text(child(response, "MessageErrors")),
        error_text(child(response, "DeliveryErrors")),
    ]
    return {
        "status": int(status_text),
        "ir_delivery_id": ir_delivery_id or False,
        "errors": "\n".join(part for part in parts if part),
        "invalid_items": invalid_items,
    }

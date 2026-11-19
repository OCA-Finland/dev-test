/** @odoo-module **/
import { Component } from "@odoo/owl";
import { useDateTimePicker } from "@web/core/datetime/datetime_hook";
import { formatDate, parseDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class VeroMonthField extends Component {
    static template = "account_vat_periods.VeroMonthField";
    static props = { ...standardFieldProps };

    setup() {
        const getPickerProps = () => ({
            type: "date",
            value: this.value,
            minPrecision: "months",
            maxPrecision: "years",
        });
        useDateTimePicker({
            format: "MM/yyyy",
            get pickerProps() {
                return getPickerProps();
            },
            onApply: (value) => this.onApply(value),
        });
        // Commit typed or cleared values before a form button saves the wizard.
        useInputField({
            refName: "start-date",
            getValue: () => this.formattedValue,
            parse: (value) => value ? parseDate(value, { format: "MM/yyyy" }).startOf("month") : false,
        });
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get formattedValue() {
        return this.value ? formatDate(this.value, { format: "MM/yyyy" }) : "";
    }

    onApply(value) {
        return this.props.record.update({
            [this.props.name]: value ? value.startOf("month") : false,
        });
    }
}

registry.category("fields").add("vero_month", {
    component: VeroMonthField,
    supportedTypes: ["date"],
});

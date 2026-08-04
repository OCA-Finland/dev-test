/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { Many2OneField, many2OneField } from '@web/views/fields/many2one/many2one_field';
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { registry } from "@web/core/registry"
import { CharField } from "@web/views/fields/char/char_field"
import { MisReportWidget } from "../../../../mis_builder/static/src/components/mis_report_widget.esm";



export class DateRangeField extends MisReportWidget {
    
    static components = { Dropdown, DropdownItem };

    setup() {
        super.setup();
        console.log("HELLO")
    }
}

DateRangeField.supportedTypes = ["char"]
DateRangeField.template = "mis_builder.DateRangeField"

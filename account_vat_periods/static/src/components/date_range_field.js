/** @odoo-module **/
import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { MisReportWidget } from "../../../../mis_builder/static/src/components/mis_report_widget.esm";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { parseDate } from "@web/core/l10n/dates";

patch(MisReportWidget.prototype, {
    setup() {
        super.setup();

        this.customM2oState = useState({
            resModel: "date.range",
            searchString: this.props.record.data.date_range_name,
            selectedId: false,
        });

    },

    async willStart() {
        super.willStart();

        const [resultShowDateRange] = await this.orm.read(
            "mis.report.instance",
            [this._instanceId()],
            ["widget_show_date_range"],
            {context: this.context}
        )

        this.widget_show_date_range = resultShowDateRange.widget_show_date_range
    },

    async onCustomM2oUpdate(selection) {
        if (!selection || selection.length === 0) {
            this.customM2oState.searchString = "";
            this.customM2oState.selectedId = false;
            this.refresh();
            return;
        }

        let selectedRecord = selection;
        if (Array.isArray(selection) && selection.length > 0) {
            selectedRecord = selection[0];
        }

        if (selectedRecord && typeof selectedRecord === 'object') {
            this.customM2oState.selectedId = selectedRecord.id || false;
            this.customM2oState.searchString = selectedRecord.display_name || "";
        }
        else if (typeof selection === "string") {
            this.customM2oState.searchString = selection;
        }

        const dateRangeId = selectedRecord.id;

        if (!dateRangeId) {
            this.state.date_range_id = "";
            return;
        }

        const displayName = selectedRecord.display_name || "";
        this.state.date_range_id = [{ id: dateRangeId, display_name: displayName }];

        const [rangeData] = await this.orm.read(
            "date.range",
            [dateRangeId],
            ["date_start"]
        );

        if (rangeData && rangeData.date_start) {
            this.state.pivot_date = parseDate(rangeData.date_start);
            this.refresh();
        }

    },

    get context() {
        return {
            ...super.context,
            date_range: this.state.date_range_id
        };
    },

    get showDateRange() {
        return this.widget_show_date_range;
    }
});

Object.assign(MisReportWidget.components, { Many2XAutocomplete });

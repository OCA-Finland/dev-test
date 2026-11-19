/** @odoo-module **/
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class VeroCredentials extends Component {
    static template = "account_vat_periods.VeroCredentials";
    static props = ["*"];

    setup() {
        this.http = useService("http");
        this.action = useService("action");
        this.key = useRef("softwareKey");
        this.transfer = useRef("transferId");
        this.password = useRef("transferPassword");
        this.recoveryKey = useRef("recoveryKey");
        this.confirmation = useRef("confirmation");
        this.acknowledge = useRef("acknowledge");
        this.state = useState({ info: null, busy: false, error: "", success: "" });
        this.backendId = this.props.action.params.backend_id;
        onWillStart(() => this.run("status"));
    }

    async run(operation, values = {}) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        this.state.success = "";
        try {
            const result = await this.http.post(`/vero/credentials/${this.backendId}/${operation}`, {
                ...values, csrf_token: odoo.csrf_token,
            });
            if (result.error) {
                this.state.error = result.error;
            } else {
                this.state.info = result;
                if (operation !== "status") {
                    this.state.success = operation === "save_key" ? _t('API key saved.') :
                        operation === "test_connection" ? _t('Connection successful: the filing period query succeeded. No tax return was submitted.') :
                        _t('Operation complete. Check the retrieval status below.');
                }
            }
        } catch {
            this.state.error = _t('Connection interrupted. Refresh the retrieval status before trying again.');
        } finally {
            // Do not retain secrets in component state, storage or error objects.
            for (const key of Object.keys(values)) {
                values[key] = "";
            }
            if (operation !== "status" && this.state.error) {
                // Re-read durable state after a failed mutation. This also hides
                // the submit form when one-use credentials may have been sent.
                try {
                    const info = await this.http.post(`/vero/credentials/${this.backendId}/status`, {
                        csrf_token: odoo.csrf_token,
                    });
                    this.state.info = info.error ? null : info;
                } catch {
                    // Require a successful status refresh before further actions.
                    this.state.info = null;
                }
            }
            this.state.busy = false;
        }
    }

    saveKey() {
        const values = { software_key: this.key.el.value.trim() };
        this.key.el.value = "";
        return this.run("save_key", values);
    }

    maintenance(operation) {
        const values = {
            confirmation: this.confirmation.el.value,
            acknowledge: this.acknowledge.el.checked ? "yes" : "no",
            encryption_key: this.recoveryKey.el.value.trim(),
        };
        this.recoveryKey.el.value = "";
        this.confirmation.el.value = "";
        this.acknowledge.el.checked = false;
        return this.run(operation, values);
    }

    submit() {
        const values = {
            transfer_id: this.transfer.el.value.trim(),
            transfer_password: this.password.el.value,
        };
        this.transfer.el.value = "";
        this.password.el.value = "";
        return this.run("submit", values);
    }

    get environmentLabel() {
        return { sandbox: _t("Sandbox"), test: _t("Test certificate"), production: _t("Production") }[this.state.info?.environment] || "";
    }

    get phaseLabel() {
        return { blocked: _t("Needs attention"), uncertain: _t("Uncertain result"), waiting: _t("Waiting for certificate"),
            ready: _t("Ready to activate"), active: _t("Activated"), rejected: _t("Rejected") }[this.state.info?.enrollment.phase] || "";
    }

    get missingVatLabel() {
        return _t("Missing - complete the company details first");
    }

    back() {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "vero.api.backend",
            res_id: this.backendId, views: [[false, "form"]], target: "current" });
    }
}

registry.category("actions").add("account_vat_periods.credentials", VeroCredentials);

/** @odoo-module **/
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
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
                    this.state.success = operation === "save_key" ? "API-avain tallennettu." :
                        operation === "test_connection" ? "Yhteys toimii: Verohallinnon kausikysely onnistui. Veroilmoitusta ei lähetetty." :
                        "Toiminto valmis. Tarkista noudon tila alta.";
                }
            }
        } catch {
            this.state.error = "Yhteys katkesi. Päivitä noudon tila ennen uutta yritystä.";
        } finally {
            // Do not retain secrets in component state, storage or error objects.
            for (const key of Object.keys(values)) {
                values[key] = "";
            }
            this.state.busy = false;
        }
    }

    saveKey() {
        const values = { software_key: this.key.el.value.trim() };
        this.key.el.value = "";
        return this.run("save_key", values);
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

    back() {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "vero.api.backend",
            res_id: this.backendId, views: [[false, "form"]], target: "current" });
    }
}

registry.category("actions").add("account_vat_periods.credentials", VeroCredentials);

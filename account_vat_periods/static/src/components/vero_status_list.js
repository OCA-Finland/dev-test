/** @odoo-module **/
import { onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

// Refresh only read-only lists. Never reload an open preview or its inputs.
export class VeroStatusListController extends ListController {
    setup() {
        super.setup();
        let timer;
        let loading = false;
        let mounted = false;
        onMounted(() => {
            mounted = true;
            timer = setInterval(async () => {
                if (!mounted || loading || document.visibilityState !== "visible" ||
                    document.querySelector(".modal") || this.model.root.editedRecord ||
                    this.model.root.selection.length) {
                    return;
                }
                loading = true;
                try {
                    await this.model.load();
                } catch {
                    // An interrupted read is safe to retry on the next tick.
                } finally {
                    loading = false;
                }
            }, 10000);
        });
        onWillUnmount(() => {
            mounted = false;
            clearInterval(timer);
        });
    }
}

registry.category("views").add("vero_status_list", {
    ...listView,
    Controller: VeroStatusListController,
});

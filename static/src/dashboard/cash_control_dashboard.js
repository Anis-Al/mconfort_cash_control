import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { formatMonetary } from "@web/views/fields/formatters";

/** Controller dashboard: KPI cards, each opening the records behind it. */
export class CashControlDashboard extends Component {
    static template = "mconfort_cash_control.CashControlDashboard";
    static components = { Layout };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ period: "30", data: null });
        this.periods = [
            ["7", _t("7 days")],
            ["30", _t("30 days")],
            ["90", _t("90 days")],
            ["all", _t("All time")],
        ];
        onWillStart(() => this.load());
    }

    get display() {
        return { controlPanel: {} };
    }

    async load() {
        this.state.data = await this.orm.call("cash.control.day", "get_dashboard_data", [this.state.period]);
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }

    money(value) {
        return formatMonetary(value, { currencyId: this.state.data.currency_id });
    }

    async open(key) {
        const action = await this.orm.call("cash.control.day", "get_dashboard_action", [key, this.state.period]);
        this.action.doAction(action);
    }

    async openDrawer() {
        const action = await this.orm.call("cash.control.day", "action_my_cash_day", []);
        // The wizard is a pop-up over this page: refresh the cards when it closes.
        this.action.doAction(action, { onClose: () => this.load() });
    }

    openAction(xmlid) {
        this.action.doAction(xmlid);
    }

    get cards() {
        const { kpis, drawer, is_controller } = this.state.data;
        const drawerCard = {
            key: "drawer",
            label: _t("Drawer now (theoretical)"),
            value: drawer === null ? _t("No cash day open") : this.money(drawer),
            sub: "",
            alert: drawer === null,
            open: () => this.openDrawer(),
        };
        if (!is_controller) {
            return [drawerCard];
        }
        const card = (key, label, value, sub, alert = false) => ({
            key, label, value, sub, alert, open: () => this.open(key),
        });
        return [
            drawerCard,
            card("days", _t("Cash difference"), this.money(kpis.days.amount),
                _t("%(count)s / %(total)s days with a difference",
                    { count: kpis.days.count, total: kpis.closed_days.count }),
                kpis.days.count > 0),
            card("payments", _t("Cash payments (net)"), this.money(kpis.payments.amount),
                _t("%(count)s payments", { count: kpis.payments.count })),
            card("refunds", _t("Cash refunds and payouts"), this.money(kpis.refunds.amount),
                _t("%(count)s payments", { count: kpis.refunds.count })),
            card("cancelled", _t("Cancelled cash payments"), String(kpis.cancelled.count),
                this.money(kpis.cancelled.amount), kpis.cancelled.count > 0),
            card("deposits_to_verify", _t("Deposits to verify (all dates)"),
                this.money(kpis.deposits_to_verify.amount),
                _t("%(count)s envelope(s)", { count: kpis.deposits_to_verify.count })),
            card("deposit_difference", _t("Deposit difference"), this.money(kpis.deposit_difference.amount),
                _t("%(count)s deposits", { count: kpis.deposit_difference.count }),
                kpis.deposit_difference.count > 0),
            card("cards", _t("Card controls to check"), String(kpis.cards.count),
                _t("Gap: %(gap)s", { gap: this.money(kpis.cards.amount) }), kpis.cards.count > 0),
        ];
    }
}

registry.category("actions").add("mconfort_cash_control.dashboard", CashControlDashboard);

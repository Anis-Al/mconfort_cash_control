from odoo import models

from .cash_control_day import CONTROLLER_GROUP

# The seller's own entries (children listed too: a blacklisted parent does not hide them).
SELLER_ONLY_MENUS = (
    'menu_my_cash_day',
    'menu_cash_control_movement',
    'menu_cash_safe_deposit',
    'menu_cash_safe_deposit_new',
    'menu_cash_safe_deposit_mine',
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        # Same hook as hr/models/ir_ui_menu.py. Controllers inherit the seller group (native Sales
        # implication) but don't work the drawer: hide the seller's entries. They still reach
        # "My Cash Day" from the dashboard's drawer card (first opening, cash brought in).
        res = super()._load_menus_blacklist()
        if self.env.user.has_group(CONTROLLER_GROUP):
            res += [
                menu.id for xmlid in SELLER_ONLY_MENUS
                if (menu := self.env.ref(f'mconfort_cash_control.{xmlid}', raise_if_not_found=False))
            ]
        return res

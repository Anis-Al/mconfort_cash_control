from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    cash_reference_float = fields.Monetary(
        string="Reference Float",
        help="Amount meant to stay in the drawer after each closing. Informational only.",
    )
    cash_control_journal_id = fields.Many2one(
        'account.journal',
        string="Controlled Cash Journal",
        domain=[('type', '=', 'cash')],
        help="Cash journal whose payments feed the cash day.",
    )
    card_control_journal_ids = fields.Many2many(
        'account.journal',
        'res_company_card_control_journal_rel',
        'company_id', 'journal_id',
        string="Card Journals",
        domain=[('type', '=', 'bank')],
        help="Validated payments of these journals are compared with the bank card totals.",
    )
    card_control_method_line_ids = fields.Many2many(
        'account.payment.method.line',
        'res_company_card_control_method_line_rel',
        'company_id', 'method_line_id',
        string="Card Payment Methods",
        help="Only count payments made with these methods. "
             "Leave empty to count every payment of the card journals.",
    )

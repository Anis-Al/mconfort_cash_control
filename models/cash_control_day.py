from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_amount

CONTROLLER_GROUP = 'sales_team.group_sale_manager'
VALIDATED_PAYMENT_STATES = ('in_process', 'paid')


class CashControlDay(models.Model):
    _name = 'cash.control.day'
    _description = "Cash Day"
    _order = 'id desc'

    # Set by the server at opening (see create) or at closing (see action_close).
    name = fields.Char(readonly=True, copy=False)
    date = fields.Date(readonly=True)
    user_id = fields.Many2one('res.users', string="Opened By", readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    journal_id = fields.Many2one('account.journal', string="Cash Journal", readonly=True)
    state = fields.Selection(
        [('open', "Open"), ('closed', "Closed")],
        default='open', required=True, readonly=True)
    closed_by = fields.Many2one('res.users', readonly=True)
    closed_at = fields.Datetime(readonly=True)
    closing_theoretical_amount = fields.Monetary(
        string="Theoretical Amount at Closing", readonly=True)

    opening_amount = fields.Monetary(
        default=lambda self: self._last_closed_day().counted_amount,
        help="Counted amount of the previous closed day. "
             "Only the very first day is typed, by a controller.")
    can_edit_opening = fields.Boolean(compute='_compute_can_edit_opening')

    payment_ids = fields.One2many('account.payment', 'cash_day_id', string="Cash Payments", readonly=True)
    movement_ids = fields.One2many('cash.control.movement', 'day_id', string="Cash In / Out", readonly=True)
    deposit_ids = fields.One2many('cash.safe.deposit', 'day_id', string="Safe Deposits", readonly=True)

    payment_in_amount = fields.Monetary(string="Cash Received", compute='_compute_amounts')
    payment_out_amount = fields.Monetary(string="Cash Paid Out", compute='_compute_amounts')
    movement_in_amount = fields.Monetary(string="Cash In", compute='_compute_amounts')
    movement_out_amount = fields.Monetary(string="Cash Out", compute='_compute_amounts')
    deposit_amount = fields.Monetary(string="Deposited in Safe", compute='_compute_amounts')
    theoretical_amount = fields.Monetary(
        compute='_compute_amounts',
        help="Live while the day is open, frozen at closing.")

    # Typed by the seller before closing.
    counted_amount = fields.Monetary()
    closing_note = fields.Text(help="Required when the counted amount differs from the theoretical amount.")
    count_gap = fields.Monetary(
        string="Gap", compute='_compute_amounts',
        help="Counted minus theoretical, shown live while counting.")

    difference = fields.Monetary(
        compute='_compute_difference', store=True,
        help="Counted amount minus theoretical amount at closing.")
    float_gap = fields.Monetary(
        compute='_compute_float_gap',
        help="Counted amount minus the reference float. Informational.")

    _one_open_day = models.UniqueIndex(
        "(company_id, journal_id) WHERE state = 'open'",
        "A cash day is already open for this cash journal.",
    )

    # -------------------------------------------------------------------------
    # COMPUTE
    # -------------------------------------------------------------------------

    @api.depends('state', 'opening_amount', 'closing_theoretical_amount', 'counted_amount',
                 'payment_ids.state', 'payment_ids.amount_company_currency_signed',
                 'movement_ids.type', 'movement_ids.amount',
                 'deposit_ids.state', 'deposit_ids.amount_declared')
    def _compute_amounts(self):
        for day in self:
            signed = day.payment_ids.filtered(
                lambda p: p.state in VALIDATED_PAYMENT_STATES).mapped('amount_company_currency_signed')
            day.payment_in_amount = sum(a for a in signed if a > 0)
            day.payment_out_amount = -sum(a for a in signed if a < 0)
            day.movement_in_amount = sum(day.movement_ids.filtered(lambda m: m.type == 'in').mapped('amount'))
            day.movement_out_amount = sum(day.movement_ids.filtered(lambda m: m.type == 'out').mapped('amount'))
            # A deposit gets its day at declaration and never changes it: it leaves the drawer once.
            day.deposit_amount = sum(day.deposit_ids.filtered(
                lambda d: d.state in ('declared', 'verified')).mapped('amount_declared'))
            live = (day.opening_amount + day.payment_in_amount - day.payment_out_amount
                    + day.movement_in_amount - day.movement_out_amount - day.deposit_amount)
            day.theoretical_amount = live if day.state == 'open' else day.closing_theoretical_amount
            day.count_gap = day.counted_amount - day.theoretical_amount

    @api.depends('state', 'counted_amount', 'closing_theoretical_amount')
    def _compute_difference(self):
        for day in self:
            day.difference = (
                day.counted_amount - day.closing_theoretical_amount if day.state == 'closed' else 0.0)

    # ponytail: reads the current reference float, so editing the setting moves past gaps too. Informational only.
    @api.depends('state', 'counted_amount', 'company_id.cash_reference_float')
    def _compute_float_gap(self):
        for day in self:
            day.float_gap = (
                day.counted_amount - day.company_id.cash_reference_float if day.state == 'closed' else 0.0)

    @api.depends_context('uid')
    def _compute_can_edit_opening(self):
        first_opening = self.env.user.has_group(CONTROLLER_GROUP) and not self._last_closed_day()
        for day in self:
            day.can_edit_opening = first_opening and not day.id

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    @api.model
    def _open_day(self, company):
        journal = company.cash_control_journal_id
        if not journal:
            return self.browse()
        return self.search([
            ('company_id', '=', company.id),
            ('journal_id', '=', journal.id),
            ('state', '=', 'open'),
        ], limit=1)

    @api.model
    def _last_closed_day(self):
        company = self.env.company
        # sudo: the opening amount is the last count, whoever closed that day; the
        # seller's record rule hides days opened by other users. Only counted_amount is read.
        return self.sudo().search([
            ('company_id', '=', company.id),
            ('journal_id', '=', company.cash_control_journal_id.id),
            ('state', '=', 'closed'),
        ], order='closed_at desc, id desc', limit=1)

    # -------------------------------------------------------------------------
    # CRUD + LOCKS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        company = self.env.company
        journal = company.cash_control_journal_id
        if not journal:
            raise UserError(_("Cash control is not configured: choose the controlled cash journal in the Sales settings."))
        clean_vals_list = []
        for vals in vals_list:
            if self._open_day(company):
                raise UserError(_("A cash day is already open for %(journal)s. Close it first.", journal=journal.display_name))
            previous = self._last_closed_day()
            if previous:
                opening = previous.counted_amount
            elif self.env.user.has_group(CONTROLLER_GROUP):
                opening = vals.get('opening_amount', 0.0)
            else:
                raise UserError(_("The first cash day must be opened by a controller, who types the opening amount."))
            # Every other value is decided here, whatever the client sent.
            clean_vals_list.append({
                'name': self.env['ir.sequence'].next_by_code('cash.control.day'),
                # User's timezone from the database, never from the request context.
                'date': fields.Datetime.context_timestamp(
                    self.with_context(tz=self.env.user.tz), fields.Datetime.now()).date(),
                'user_id': self.env.uid,
                'company_id': company.id,
                'journal_id': journal.id,
                'opening_amount': opening,
            })
        return super().create(clean_vals_list)

    def write(self, vals):
        if set(vals) - {'counted_amount', 'closing_note'}:
            raise UserError(_("Only the counted amount and the closing note can be typed on a cash day."))
        if any(day.state != 'open' for day in self):
            raise UserError(_("A closed cash day cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError(_("Cash days cannot be deleted."))

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    @api.model
    def action_my_cash_day(self):
        """'My Cash Day' is the pop-up wizard; this full form stays as the detail/history page."""
        return self.env['cash.control.day.wizard'].action_open_wizard()

    def action_open_day(self):
        # The form saves (creates) the record before calling a button: opening is done by create().
        return True

    def action_close(self):
        for day in self:
            if day.state != 'open':
                raise UserError(_("This cash day is already closed."))
            theoretical = day.theoretical_amount
            gap = day.counted_amount - theoretical
            if not day.currency_id.is_zero(gap) and not (day.closing_note or '').strip():
                raise UserError(_(
                    "The counted amount differs from the theoretical amount by %(gap)s. "
                    "Explain the difference in the closing note before closing.",
                    gap=format_amount(self.env, gap, day.currency_id),
                ))
            # super().write: the state and closing fields are refused by write() on purpose.
            super(CashControlDay, day).write({
                'state': 'closed',
                'closing_theoretical_amount': theoretical,
                'closed_by': self.env.uid,
                'closed_at': fields.Datetime.now(),
            })
        return True

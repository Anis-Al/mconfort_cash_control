from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .cash_control_day import CONTROLLER_GROUP


class CashSafeDeposit(models.Model):
    _name = 'cash.safe.deposit'
    _description = "Safe Deposit"
    _order = 'id desc'

    # Timestamps are hidden from sellers (spec §6.5): field groups also cover list,
    # export, read/search_read, search domains and group by.
    create_date = fields.Datetime(string="Created on", readonly=True, groups=CONTROLLER_GROUP)
    write_date = fields.Datetime(string="Last Updated on", readonly=True, groups=CONTROLLER_GROUP)

    # Set by the server (create / action_declare / action_verify).
    name = fields.Char(readonly=True, copy=False, help="Number written on the envelope, given at declaration.")
    user_id = fields.Many2one('res.users', string="Seller", readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    day_id = fields.Many2one('cash.control.day', string="Cash Day", readonly=True, index='btree_not_null')
    state = fields.Selection(
        [('draft', "Draft"), ('declared', "Declared"), ('verified', "Verified")],
        default='draft', required=True, readonly=True)
    declared_at = fields.Datetime(readonly=True, groups=CONTROLLER_GROUP)
    verified_by = fields.Many2one('res.users', readonly=True)
    verified_at = fields.Datetime(readonly=True, groups=CONTROLLER_GROUP)

    line_ids = fields.One2many('cash.safe.deposit.line', 'deposit_id', string="Orders")
    amount_declared = fields.Monetary(compute='_compute_amount_declared', store=True)

    # Typed by a controller while the deposit is declared.
    amount_counted = fields.Monetary()
    verification_note = fields.Text()
    difference = fields.Monetary(
        compute='_compute_difference', store=True,
        help="Counted amount minus declared amount, once verified.")

    @api.depends('line_ids.amount')
    def _compute_amount_declared(self):
        for deposit in self:
            deposit.amount_declared = sum(deposit.line_ids.mapped('amount'))

    @api.depends('state', 'amount_counted', 'amount_declared')
    def _compute_difference(self):
        for deposit in self:
            deposit.difference = (
                deposit.amount_counted - deposit.amount_declared if deposit.state == 'verified' else 0.0)

    @api.depends('name')
    def _compute_display_name(self):
        for deposit in self:
            deposit.display_name = deposit.name or _("Draft Deposit")

    # -------------------------------------------------------------------------
    # CRUD + LOCKS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # Only the lines come from the client.
        return super().create([
            {'line_ids': vals.get('line_ids', []), 'user_id': self.env.uid, 'company_id': self.env.company.id}
            for vals in vals_list
        ])

    def write(self, vals):
        is_controller = self.env.user.has_group(CONTROLLER_GROUP)
        for deposit in self:
            if deposit.state == 'draft':
                allowed = {'line_ids'}
            elif deposit.state == 'declared' and is_controller:
                allowed = {'amount_counted', 'verification_note'}
            else:
                allowed = set()
            if set(vals) - allowed:
                raise UserError(_(
                    "%(deposit)s cannot be changed this way: lines are typed before declaration, "
                    "the counted amount and note by a controller before verification.",
                    deposit=deposit.display_name,
                ))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(deposit.state != 'draft' for deposit in self):
            raise UserError(_("A declared deposit cannot be deleted."))

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_declare(self):
        for deposit in self:
            if deposit.state != 'draft':
                raise UserError(_("%(deposit)s is already declared.", deposit=deposit.display_name))
            if not deposit.line_ids:
                raise UserError(_("Add at least one order to the deposit."))
            day = self.env['cash.control.day']._open_day(deposit.company_id)
            if not day:
                raise UserError(_("No cash day is open. Open the cash day before declaring a deposit."))
            # sudo: the seller declares, but declared_at is a Controller-only field (spec §6.5),
            # so the seller's own write would be refused. Every value here is server-made.
            super(CashSafeDeposit, deposit.sudo()).write({
                'name': self.env['ir.sequence'].next_by_code('cash.safe.deposit'),
                'day_id': day.id,
                'declared_at': fields.Datetime.now(),
                'state': 'declared',
            })
        return True

    def action_verify(self):
        if not self.env.user.has_group(CONTROLLER_GROUP):
            raise AccessError(_("Only a controller can verify a deposit."))
        for deposit in self:
            if deposit.state != 'declared':
                raise UserError(_("Only a declared deposit can be verified."))
            if deposit.currency_id.is_zero(deposit.amount_counted) and not (deposit.verification_note or '').strip():
                raise UserError(_("Type the counted amount. For an empty envelope, explain it in the verification note."))
            # Verification only records the count: no balance moves, nothing else is created.
            super(CashSafeDeposit, deposit).write({
                'state': 'verified',
                'verified_by': self.env.uid,
                'verified_at': fields.Datetime.now(),
            })
        return True


class CashSafeDepositLine(models.Model):
    _name = 'cash.safe.deposit.line'
    _description = "Safe Deposit Line"
    _order = 'id'

    create_date = fields.Datetime(string="Created on", readonly=True, groups=CONTROLLER_GROUP)
    write_date = fields.Datetime(string="Last Updated on", readonly=True, groups=CONTROLLER_GROUP)

    deposit_id = fields.Many2one('cash.safe.deposit', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='deposit_id.company_id', store=True)
    currency_id = fields.Many2one(related='deposit_id.currency_id')
    sale_order_id = fields.Many2one('sale.order', string="Order", required=True)
    amount = fields.Monetary(required=True)

    _amount_positive = models.Constraint('CHECK(amount > 0)', "The amount must be positive.")
    _order_once = models.Constraint(
        'UNIQUE(deposit_id, sale_order_id)', "An order can appear only once in a deposit.")

    def _check_deposit_draft(self, deposits):
        if any(deposit.state != 'draft' for deposit in deposits):
            raise UserError(_("The lines of a declared deposit cannot be changed."))

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [
            {key: vals[key] for key in ('deposit_id', 'sale_order_id', 'amount') if key in vals}
            for vals in vals_list
        ]
        self._check_deposit_draft(self.env['cash.safe.deposit'].browse(
            {vals['deposit_id'] for vals in vals_list if vals.get('deposit_id')}))
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - {'sale_order_id', 'amount'}:
            raise UserError(_("Only the order and the amount of a deposit line can be changed."))
        self._check_deposit_draft(self.deposit_id)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        self._check_deposit_draft(self.deposit_id)

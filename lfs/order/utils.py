# lfs imports
import lfs.voucher.utils
from lfs.cart import utils as cart_utils
from lfs.core.signals import order_submitted
from lfs.customer import utils as customer_utils
from lfs.order.models import Order
from lfs.order.models import OrderItem
from lfs.payment import utils as payment_utils
from lfs.shipping import utils as shipping_utils
from lfs.voucher.models import Voucher

def add_order(request):
    """Adds an order based on current cart for the current customer.

    It assumes that the customer is prepared with all needed information. This
    is within the responsibility of the checkout form.
    """
    customer = customer_utils.get_customer(request)
    order = None

    invoice_address = customer.selected_invoice_address
    if customer.selected_shipping_address:
        shipping_address = customer.selected_shipping_address
    else:
        shipping_address = customer.selected_invoice_address

    cart = cart_utils.get_cart(request)
    if cart is None:
        return order
    cart_costs = cart_utils.get_cart_costs(request, cart, total=False)

    shipping_method = shipping_utils.get_selected_shipping_method(request)
    shipping_costs = shipping_utils.get_shipping_costs(request, shipping_method)

    payment_method = payment_utils.get_selected_payment_method(request)
    payment_costs = payment_utils.get_payment_costs(request, payment_method)

    # Set email dependend on login state. An anonymous customer doesn't  have a
    # django user account, so we set the name of the invoice address to the
    # customer name.

    # Note: After this has been processed the order's customer email has an
    # email in any case. That means you can use it to send emails to the
    # customer.
    if request.user.is_authenticated():
        user = request.user
        customer_email = user.email
    else:
        user = None
        customer_email = customer.selected_invoice_email

    # Calculate the totals
    price = cart_costs["price"] + shipping_costs["price"] + payment_costs["price"]
    tax = cart_costs["tax"] + shipping_costs["tax"] + payment_costs["tax"]

    # Add voucher if one exists
    try:
        voucher_number = lfs.voucher.utils.get_current_voucher_number(request)
        voucher = Voucher.objects.get(number=voucher_number)
    except Voucher.DoesNotExist:
        voucher = None
    else:
        is_voucher_effective, voucher_message = voucher.is_effective(cart)
        if is_voucher_effective:
            voucher_number = voucher.number
            voucher_price = voucher.get_price_gross(cart)
            voucher_tax = voucher.get_tax(cart)

            price -= voucher_price
            tax -= voucher_tax
        else:
            voucher = None

    order = Order.objects.create(
        user = user,
        session = request.session.session_key,
        price = price,
        tax = tax,

        customer_firstname = invoice_address.firstname,
        customer_lastname = invoice_address.lastname,
        customer_email = customer_email,

        shipping_method = shipping_method,
        shipping_price = shipping_costs["price"],
        shipping_tax = shipping_costs["tax"],
        payment_method = payment_method,
        payment_price = payment_costs["price"],
        payment_tax = payment_costs["tax"],

        invoice_firstname = invoice_address.firstname,
        invoice_lastname = invoice_address.lastname,
        invoice_line1 = invoice_address.line1,
        invoice_line2 = invoice_address.line2,
        invoice_line3 = invoice_address.line3,
        invoice_line4 = invoice_address.line4,
        invoice_line5 = invoice_address.line5,
        invoice_country = invoice_address.country,
        invoice_phone = customer.selected_invoice_phone,

        shipping_firstname = shipping_address.firstname,
        shipping_lastname = shipping_address.lastname,
        shipping_line1 = shipping_address.line1,
        shipping_line2 = shipping_address.line2,
        shipping_line3 = shipping_address.line3,
        shipping_line4 = shipping_address.line4,
        shipping_line5 = shipping_address.line5,
        shipping_country = shipping_address.country,
        shipping_phone = customer.selected_shipping_phone,

        message = request.POST.get("message", ""),
    )

    requested_delivery_date = request.POST.get("requested_delivery_date", None)
    if requested_delivery_date is not None:
        order.requested_delivery_date = requested_delivery_date
        order.save()

    if voucher:
        voucher.mark_as_used()
        order.voucher_number = voucher_number
        order.voucher_price = voucher_price
        order.voucher_tax = voucher_tax
        order.save()

    # Copy bank account if one exists
    if customer.selected_bank_account:
        bank_account = customer.selected_bank_account
        order.account_number = bank_account.account_number
        order.bank_identification_code = bank_account.bank_identification_code
        order.bank_name = bank_account.bank_name
        order.depositor = bank_account.depositor

    order.save()

    # Copy cart items
    for cart_item in cart.cartitem_set.all():
        OrderItem.objects.create(
            order=order,

            price_net = cart_item.get_price_net(),
            price_gross = cart_item.get_price_gross(),
            tax = cart_item.get_tax(),

            product = cart_item.product,
            product_sku = cart_item.product.sku,
            product_name = cart_item.product.get_name(),
            product_amount=cart_item.amount,
            product_price_net = cart_item.product.get_price_net(),
            product_price_gross = cart_item.product.get_price_gross(),
            product_tax = cart_item.product.get_tax(),
        )

        cart_item.product.decrease_stock_amount(cart_item.amount)

    cart.delete()
    order_submitted.send({"order" : order, "request" : request})

    # Note: Save order for later use in thank you page. The order will be
    # removed from the session if the thank you page has been called.
    request.session["order"] = order

    return order


"""Product catalogue and seller inventory (Stage 2).

Public catalogue browsing plus protected product registration and stock
management for sellers and administrators.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from .. import models, security
from ..i18n import t
from ..security import roles_required

product_bp = Blueprint("product", __name__)


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config[
        "ALLOWED_IMAGE_EXTENSIONS"
    ]


def _save_image(file_storage) -> str | None:
    """Store an uploaded image and return the path relative to the instance folder."""
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_file(file_storage.filename):
        return None
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    original = secure_filename(file_storage.filename)
    extension = original.rsplit(".", 1)[1].lower()
    name = f"{secrets.token_hex(8)}.{extension}"
    destination = upload_folder / name
    file_storage.save(destination)
    return f"uploads/products/{name}"


def _delete_image(image_path: str | None) -> None:
    if not image_path:
        return
    try:
        Path(current_app.config["UPLOAD_FOLDER"], Path(image_path).name).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------
# Public catalogue
# ---------------------------------------------------------------------
@product_bp.route("/products")
def catalogue():
    search = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    sort = (request.args.get("sort") or "newest").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 12
    total = models.count_products(active_only=True, search=search, category=category)
    pages = max(1, -(-total // per_page))
    page = min(max(page, 1), pages)
    products = models.list_products(
        active_only=True, search=search, category=category, sort=sort,
        limit=per_page, offset=(page - 1) * per_page,
    )
    user = security.current_user()
    fav_ids = models.favorite_ids(user["id"]) if (user and user["role"] == "buyer") else set()
    return render_template(
        "product/catalogue.html",
        products=products,
        search=search,
        category=category,
        sort=sort,
        categories=models.list_categories(),
        page=page,
        pages=pages,
        total=total,
        fav_ids=fav_ids,
    )


@product_bp.route("/products/<int:product_id>")
def product_detail(product_id: int):
    product = models.get_product(product_id)
    if product is None or not product["is_active"]:
        abort(404)
    user = security.current_user()
    can_review = (
        user is not None and user["role"] == "buyer"
        and models.buyer_purchased(user["id"], product_id)
    )
    return render_template(
        "product/detail.html",
        product=product,
        rating=models.product_rating(product_id),
        reviews=models.product_reviews(product_id),
        can_review=can_review,
        is_favorite=(models.is_favorite(user["id"], product_id)
                     if (user and user["role"] == "buyer") else False),
    )


@product_bp.route("/uploads/products/<path:filename>")
def product_image(filename: str):
    # image_path is stored as "uploads/products/<name>"; only the file name
    # lives inside UPLOAD_FOLDER, so strip any directory prefix.
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], Path(filename).name, conditional=True
    )


# ---------------------------------------------------------------------
# Favorites (buyers only)
# ---------------------------------------------------------------------
@product_bp.route("/products/<int:product_id>/favorite", methods=["POST"])
def toggle_favorite(product_id: int):
    user = security.current_user()
    if user is None:
        return jsonify(ok=False, error=t("flash.sign_in_required")), 401
    if user["role"] != "buyer":
        return jsonify(ok=False, error=t("fav.buyers_only")), 403
    if models.get_product(product_id) is None:
        return jsonify(ok=False, error=t("cart.err.product_not_found")), 404

    is_fav = models.toggle_favorite(user["id"], product_id)
    return jsonify(ok=True, favorite=is_fav,
                   count=models.count_favorites(user["id"]))


@product_bp.route("/favorites")
def favorites():
    """The buyer's favourited products."""
    user = security.current_user()
    if user is None or user["role"] != "buyer":
        flash(t("fav.buyers_only"), "warning")
        return redirect(url_for("product.catalogue"))
    products = models.list_favorites(user["id"])
    fav_ids = models.favorite_ids(user["id"])
    return render_template("product/favorites.html", products=products,
                           fav_ids=fav_ids)


# ---------------------------------------------------------------------
# Seller / administrator inventory
# ---------------------------------------------------------------------
@product_bp.route("/seller/products")
@roles_required("admin", "seller")
def seller_products():
    user = security.current_user()
    if user["role"] == "admin":
        products = models.list_products(active_only=False)
    else:
        products = models.list_products(active_only=False, seller_id=user["id"])
    return render_template(
        "product/list.html",
        products=products,
        is_admin=user["role"] == "admin",
    )


@product_bp.route("/products/<int:product_id>/review", methods=["POST"])
@roles_required("buyer")
def review_product(product_id: int):
    """Verified buyers rate and review a product they purchased."""
    user = security.current_user()
    if not models.buyer_purchased(user["id"], product_id):
        flash(t("flash.review_not_allowed"), "error")
        return redirect(url_for("product.product_detail", product_id=product_id))

    rating = request.form.get("rating", type=int)
    comment = (request.form.get("comment") or "").strip()
    if models.add_review(product_id, user["id"], rating, comment):
        models.log_audit(
            "review_posted", user["id"], user["username"],
            f"product={product_id} rating={rating}", security.client_ip(),
        )
        flash(t("flash.review_saved"), "success")
    else:
        flash(t("err.review_rating"), "error")
    return redirect(url_for("product.product_detail", product_id=product_id))


@product_bp.route("/seller/products/register", methods=["GET", "POST"])
@roles_required("admin", "seller")
def register_product():
    user = security.current_user()
    form = {
        "name": "",
        "description": "",
        "category": "",
        "price": "",
        "stock": "",
        "discount": "0",
        "image": "",
    }
    errors: dict[str, str] = {}

    if request.method == "POST":
        form = {
            "name": (request.form.get("name") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "category": (request.form.get("category") or "").strip(),
            "price": (request.form.get("price") or "").strip(),
            "stock": (request.form.get("stock") or "").strip(),
            "discount": (request.form.get("discount") or "0").strip(),
        }
        uploaded_image = request.files.get("image")

        if not form["name"]:
            errors["name"] = t("err.product_name_required")
        if len(form["name"]) > 120:
            errors["name"] = t("err.product_name_long")
        if len(form["category"]) > 60:
            errors["category"] = t("err.category_long")

        try:
            price_cents = int(round(float(form["price"]) * 100)) if form["price"] else None
        except ValueError:
            price_cents = None
            errors["price"] = t("err.price_required")
        if price_cents is not None and price_cents <= 0:
            errors["price"] = t("err.price_positive")

        try:
            discount = int(form["discount"]) if form["discount"] != "" else 0
        except ValueError:
            discount = -1
        if discount < 0 or discount > models.DISCOUNT_MAX_PERCENT:
            errors["discount"] = t("err.discount_range", max=models.DISCOUNT_MAX_PERCENT)

        try:
            stock = int(form["stock"]) if form["stock"] != "" else None
        except ValueError:
            stock = None
        if stock is None:
            errors["stock"] = t("err.stock_required")
        elif stock < 0:
            errors["stock"] = t("err.stock_non_negative")

        if uploaded_image and uploaded_image.filename:
            if not _allowed_file(uploaded_image.filename):
                errors["image"] = t("err.invalid_image")
        elif not request.form.get("existing_image"):
            errors["image"] = t("err.image_required")

        if not errors:
            image_path = _save_image(uploaded_image) if uploaded_image else None
            product_id = models.create_product(
                seller_id=user["id"],
                name=form["name"],
                description=form["description"],
                category=form["category"],
                price_cents=price_cents,
                stock_quantity=stock,
                image_path=image_path,
            )
            if discount:
                models.set_product_discount(product_id, discount)
            models.log_audit(
                "product_registered",
                user["id"],
                user["username"],
                f"product={product_id} name={form['name']}",
                security.client_ip(),
            )
            flash(t("flash.product_registered"), "success")
            return redirect(url_for("product.seller_products"))

        flash(t("flash.fix_fields"), "error")

    return render_template(
        "product/register.html",
        form=form,
        errors=errors,
        existing_categories=models.list_categories(),
    )


@product_bp.route("/seller/products/<int:product_id>/edit", methods=["GET", "POST"])
@roles_required("admin", "seller")
def edit_product(product_id: int):
    user = security.current_user()
    product = models.get_product(product_id)
    if product is None:
        abort(404)
    if user["role"] != "admin" and product["seller_id"] != user["id"]:
        models.log_audit(
            "access_denied", user["id"], user["username"],
            f"product edit {product_id} not owned", security.client_ip(),
        )
        return (
            render_template(
                "errors/403.html",
                required_roles=("owner", "admin"),
                user_role=user["role"],
            ),
            403,
        )

    form = {
        "name": product["name"],
        "description": product["description"] or "",
        "category": product["category"] or "",
        "price": f"{product['price_cents'] / 100:.2f}",
        "stock": str(product["stock_quantity"]),
        "discount": str(product["discount_percent"] or 0),
    }
    errors: dict[str, str] = {}

    if request.method == "POST":
        form = {
            "name": (request.form.get("name") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "category": (request.form.get("category") or "").strip(),
            "price": (request.form.get("price") or "").strip(),
            "stock": (request.form.get("stock") or "").strip(),
            "discount": (request.form.get("discount") or "0").strip(),
        }
        uploaded_image = request.files.get("image")

        if not form["name"]:
            errors["name"] = t("err.product_name_required")
        if len(form["category"]) > 60:
            errors["category"] = t("err.category_long")

        try:
            price_cents = int(round(float(form["price"]) * 100)) if form["price"] else None
        except ValueError:
            price_cents = None
            errors["price"] = t("err.price_required")
        if price_cents is not None and price_cents <= 0:
            errors["price"] = t("err.price_positive")

        try:
            stock = int(form["stock"]) if form["stock"] != "" else None
        except ValueError:
            stock = None
        if stock is None:
            errors["stock"] = t("err.stock_required")
        elif stock < 0:
            errors["stock"] = t("err.stock_non_negative")

        if uploaded_image and uploaded_image.filename and not _allowed_file(uploaded_image.filename):
            errors["image"] = t("err.invalid_image")

        try:
            discount = int(form["discount"]) if form["discount"] != "" else 0
        except ValueError:
            discount = -1
        if discount < 0 or discount > models.DISCOUNT_MAX_PERCENT:
            errors["discount"] = t("err.discount_range", max=models.DISCOUNT_MAX_PERCENT)

        if not errors:
            image_path = product["image_path"]
            if uploaded_image and uploaded_image.filename:
                _delete_image(image_path)
                image_path = _save_image(uploaded_image)
            models.update_product(
                product_id,
                name=form["name"],
                description=form["description"],
                category=form["category"],
                price_cents=price_cents,
                stock_quantity=stock,
                image_path=image_path,
            )
            models.set_product_discount(product_id, discount)
            models.log_audit(
                "product_updated",
                user["id"],
                user["username"],
                f"product={product_id}",
                security.client_ip(),
            )
            flash(t("flash.product_updated"), "success")
            return redirect(url_for("product.seller_products"))

        flash(t("flash.fix_fields"), "error")

    return render_template(
        "product/register.html",
        form=form,
        errors=errors,
        product=product,
        editing=True,
        existing_categories=models.list_categories(),
    )


@product_bp.route("/seller/products/<int:product_id>/delete", methods=["POST"])
@roles_required("admin", "seller")
def delete_product(product_id: int):
    user = security.current_user()
    product = models.get_product(product_id)
    if product is None:
        abort(404)
    if user["role"] != "admin" and product["seller_id"] != user["id"]:
        models.log_audit(
            "access_denied", user["id"], user["username"],
            f"product delete {product_id} not owned", security.client_ip(),
        )
        return (
            render_template(
                "errors/403.html",
                required_roles=("owner", "admin"),
                user_role=user["role"],
            ),
            403,
        )
    _delete_image(product["image_path"])
    models.delete_product(product_id)
    models.log_audit(
        "product_deleted", user["id"], user["username"],
        f"product={product_id} name={product['name']}", security.client_ip(),
    )
    flash(t("flash.product_deleted"), "success")
    return redirect(url_for("product.seller_products"))

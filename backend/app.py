"""SpendWise AI API starter. All money is stored as Decimal-backed NUMERIC."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, Numeric, func, inspect, make_url, text
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Family(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Membership(db.Model):
    __tablename__ = "family_memberships"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    family_id = db.Column(db.Integer, db.ForeignKey("family.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="member")
    __table_args__ = (CheckConstraint("role in ('admin','member')", name="valid_membership_role"),)

class FamilyProfile(db.Model):
    __tablename__ = "family_profiles"
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey("family.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    pin_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (CheckConstraint("role in ('admin','member')", name="valid_profile_role"),)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey("family.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("family_profiles.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    amount = db.Column(Numeric(12, 2), nullable=False)
    occurred_on = db.Column(db.Date, nullable=False, index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (CheckConstraint("kind in ('income','expense')", name="valid_transaction_kind"), CheckConstraint("amount > 0", name="positive_amount"))

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey("family.id", ondelete="CASCADE"), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False, default="Overall")
    amount = db.Column(Numeric(12, 2), nullable=False)
    month = db.Column(db.String(7), nullable=False)
    __table_args__ = (CheckConstraint("amount > 0", name="positive_budget"), db.UniqueConstraint("owner_id", "category", "month", name="unique_user_month_category"))

def create_app(test_config=None):
    app = Flask(__name__)
    database_url = make_url(os.getenv("DATABASE_URL", "sqlite:///instance/spendwise.db"))
    if database_url.get_backend_name() == "sqlite" and database_url.database and not Path(database_url.database).is_absolute():
        database_path = (Path(__file__).resolve().parent.parent / database_url.database).resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_url = database_url.set(database=str(database_path))
    app.config.update(SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"), SQLALCHEMY_DATABASE_URI=database_url.render_as_string(hide_password=False), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true", MAX_CONTENT_LENGTH=2 * 1024 * 1024)
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    Migrate(app, db)
    CORS(app, origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")], supports_credentials=True)
    limiter = Limiter(get_remote_address, app=app, default_limits=[])

    @app.before_request
    def load_identity():
        uid = session.get("uid")
        g.user = db.session.get(User, uid) if uid else None
        g.membership = Membership.query.filter_by(user_id=uid).first() if uid else None
        profile_id = session.get("profile_id")
        g.profile = db.session.get(FamilyProfile, profile_id) if profile_id else None
        if g.profile and (not g.membership or g.profile.owner_user_id != uid or g.profile.family_id != g.membership.family_id):
            session.pop("profile_id", None)
            g.profile = None

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user or not g.membership:
                return jsonify(error="Authentication required"), 401
            return fn(*args, **kwargs)
        return wrapped

    def profiled(fn):
        @wraps(fn)
        @authenticated
        def wrapped(*args, **kwargs):
            if not g.profile:
                return jsonify(error="Select a family profile to continue."), 403
            return fn(*args, **kwargs)
        return wrapped

    def json_error(message, status): return jsonify(error=message), status

    @app.get("/api/health")
    def health(): return jsonify(status="ok")

    @app.post("/api/auth/signup")
    def signup():
        body = request.get_json(silent=True) or {}
        name, email, password, family_name = [str(body.get(k, "")).strip() for k in ("name", "email", "password", "family_name")]
        if not name or "@" not in email or len(password) < 10 or not family_name:
            return json_error("Enter your name, a valid email, a family name, and a password of at least 10 characters.", 400)
        if User.query.filter(func.lower(User.email) == email.lower()).first(): return json_error("An account with this email already exists.", 409)
        user = User(name=name, email=email.lower(), password_hash=generate_password_hash(password))
        family = Family(name=family_name)
        db.session.add_all([user, family]); db.session.flush()
        db.session.add(Membership(user_id=user.id, family_id=family.id, role="admin"))
        db.session.add(FamilyProfile(owner_user_id=user.id, family_id=family.id, display_name=name, role="admin"))
        db.session.commit(); session.clear(); session["uid"] = user.id
        return jsonify(user={"name": user.name, "email": user.email}, family={"name": family.name}, role="admin"), 201

    @app.post("/api/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, str(body.get("password", ""))): return json_error("Email or password is incorrect.", 401)
        session.clear(); session["uid"] = user.id
        membership = Membership.query.filter_by(user_id=user.id).first()
        if not membership: session.clear(); return json_error("This account has no active family membership.", 403)
        profile = FamilyProfile.query.filter_by(owner_user_id=user.id, family_id=membership.family_id).first()
        if not profile:
            profile = FamilyProfile(owner_user_id=user.id, family_id=membership.family_id, display_name=user.name, role=membership.role)
            db.session.add(profile); db.session.flush()
        # Existing single-user transactions stay with that user's original profile.
        Transaction.query.filter_by(owner_id=user.id, family_id=membership.family_id, profile_id=None).update({"profile_id":profile.id})
        db.session.commit()
        return jsonify(user={"name": user.name, "email": user.email}, role=membership.role, family_name=db.session.get(Family, membership.family_id).name)

    @app.post("/api/auth/logout")
    def logout(): session.clear(); return "", 204

    @app.get("/api/me")
    @authenticated
    def me(): return jsonify(name=g.user.name, email=g.user.email, role=g.profile.role if g.profile else g.membership.role, family_name=db.session.get(Family, g.membership.family_id).name, profile={"id":g.profile.id,"name":g.profile.display_name,"role":g.profile.role} if g.profile else None)

    @app.get("/api/profiles")
    @authenticated
    def list_profiles():
        profiles = FamilyProfile.query.filter_by(owner_user_id=g.user.id, family_id=g.membership.family_id).order_by(FamilyProfile.id).all()
        return jsonify(items=[{"id":p.id,"name":p.display_name,"role":p.role,"pin_set":bool(p.pin_hash)} for p in profiles], can_add=g.membership.role == "admin")

    @app.post("/api/profiles/select")
    @limiter.limit("8 per minute")
    @authenticated
    def select_profile():
        body = request.get_json(silent=True) or {}
        profile = FamilyProfile.query.filter_by(id=body.get("profile_id"), owner_user_id=g.user.id, family_id=g.membership.family_id).first()
        pin = str(body.get("pin", ""))
        if not profile: return json_error("Profile not found.", 404)
        if not pin.isdigit() or not 4 <= len(pin) <= 8: return json_error("Enter a PIN with 4 to 8 digits.", 400)
        if profile.pin_hash and not check_password_hash(profile.pin_hash, pin): return json_error("That PIN is incorrect.", 401)
        if not profile.pin_hash:
            profile.pin_hash = generate_password_hash(pin)
            db.session.commit()
        session["profile_id"] = profile.id
        return jsonify(profile={"id":profile.id,"name":profile.display_name,"role":profile.role}, role=profile.role, family_name=db.session.get(Family, profile.family_id).name)

    @app.post("/api/profiles/lock")
    @authenticated
    def lock_profile():
        session.pop("profile_id", None)
        return "", 204

    @app.post("/api/profiles")
    @authenticated
    def create_profile():
        if g.membership.role != "admin" or (g.profile and g.profile.role != "admin"):
            return json_error("Administrator access required.", 403)
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        if not name or len(name) > 100: return json_error("Enter a profile name up to 100 characters.", 400)
        profile = FamilyProfile(owner_user_id=g.user.id, family_id=g.membership.family_id, display_name=name, role="member")
        db.session.add(profile); db.session.commit()
        return jsonify(id=profile.id, name=profile.display_name, role=profile.role, pin_set=False), 201

    @app.post("/api/profiles/change-pin")
    @profiled
    def change_profile_pin():
        body = request.get_json(silent=True) or {}
        current, new = str(body.get("current_pin", "")), str(body.get("new_pin", ""))
        if not new.isdigit() or not 4 <= len(new) <= 8: return json_error("New PIN must contain 4 to 8 digits.", 400)
        if g.profile.pin_hash and (not current or not check_password_hash(g.profile.pin_hash, current)): return json_error("Current PIN is incorrect.", 401)
        g.profile.pin_hash = generate_password_hash(new); db.session.commit()
        return jsonify(message="PIN updated.")

    @app.post("/api/profiles/reset-pin")
    @limiter.limit("5 per minute")
    @authenticated
    def reset_profile_pin():
        # This recovery route is available only before profile selection or from an admin profile.
        if g.membership.role != "admin" or (g.profile and g.profile.role != "admin"):
            return json_error("Administrator access required to reset a family profile PIN.", 403)
        body = request.get_json(silent=True) or {}
        if not check_password_hash(g.user.password_hash, str(body.get("account_password", ""))):
            return json_error("Account password is incorrect.", 401)
        pin = str(body.get("new_pin", ""))
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            return json_error("New PIN must contain 4 to 8 digits.", 400)
        profile = FamilyProfile.query.filter_by(id=body.get("profile_id"), owner_user_id=g.user.id, family_id=g.membership.family_id).first()
        if not profile:
            return json_error("Profile not found.", 404)
        profile.pin_hash = generate_password_hash(pin)
        db.session.commit()
        return jsonify(message="PIN reset. Enter the new PIN to open the profile.")

    @app.delete("/api/profiles/<int:profile_id>")
    @authenticated
    def delete_family_profile(profile_id):
        if g.membership.role != "admin" or not g.profile or g.profile.role != "admin":
            return json_error("Administrator profile access required to remove a family member.", 403)
        profile = FamilyProfile.query.filter_by(
            id=profile_id, owner_user_id=g.user.id, family_id=g.membership.family_id
        ).first()
        if not profile:
            return json_error("Family profile not found.", 404)
        if profile.role == "admin":
            return json_error("The administrator profile cannot be removed here. Delete the household account instead.", 400)
        body = request.get_json(silent=True) or {}
        if not check_password_hash(g.user.password_hash, str(body.get("account_password", ""))):
            return json_error("Account password is incorrect.", 401)
        if str(body.get("confirm_name", "")).strip() != profile.display_name:
            return json_error("Enter the family member's name exactly to confirm deletion.", 400)
        profile_name = profile.display_name
        Transaction.query.filter_by(
            owner_id=g.user.id, family_id=g.membership.family_id, profile_id=profile.id
        ).delete(synchronize_session=False)
        db.session.delete(profile)
        db.session.commit()
        return jsonify(message=f"{profile_name}'s profile and transactions were deleted.")

    @app.delete("/api/account")
    @authenticated
    def delete_household_account():
        if g.membership.role != "admin" or not g.profile or g.profile.role != "admin":
            return json_error("Select the administrator profile to delete this household account.", 403)
        body = request.get_json(silent=True) or {}
        if not check_password_hash(g.user.password_hash, str(body.get("account_password", ""))):
            return json_error("Account password is incorrect.", 401)
        if str(body.get("confirmation", "")).strip().lower() != g.user.email.lower():
            return json_error("Enter your account email exactly to confirm deletion.", 400)

        user_id, family_id = g.user.id, g.membership.family_id
        other_memberships = Membership.query.filter(
            Membership.family_id == family_id, Membership.user_id != user_id
        ).count()
        if other_memberships:
            return json_error("This family has other linked accounts. Transfer administrator access before deleting this account.", 409)

        Transaction.query.filter_by(owner_id=user_id, family_id=family_id).delete(synchronize_session=False)
        Budget.query.filter_by(owner_id=user_id, family_id=family_id).delete(synchronize_session=False)
        FamilyProfile.query.filter_by(owner_user_id=user_id, family_id=family_id).delete(synchronize_session=False)
        Membership.query.filter_by(user_id=user_id, family_id=family_id).delete(synchronize_session=False)
        user = db.session.get(User, user_id)
        family = db.session.get(Family, family_id)
        if user:
            db.session.delete(user)
        if family:
            db.session.delete(family)
        db.session.commit()
        session.clear()
        return jsonify(message="Your household account and its data were deleted.")

    def parse_period():
        start = request.args.get("start"); end = request.args.get("end")
        try: return (date.fromisoformat(start) if start else date.today().replace(day=1), date.fromisoformat(end) if end else date.today())
        except ValueError: raise ValueError("Dates must use YYYY-MM-DD format.")

    @app.get("/api/transactions")
    @profiled
    def list_transactions():
        query = Transaction.query.filter_by(owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id)
        kind = request.args.get("kind")
        if kind in ("income", "expense"): query = query.filter_by(kind=kind)
        if request.args.get("category"): query = query.filter_by(category=request.args["category"])
        try:
            start, end = parse_period()
            query = query.filter(Transaction.occurred_on >= start, Transaction.occurred_on <= end)
        except ValueError as e: return json_error(str(e), 400)
        page = max(1, request.args.get("page", 1, type=int)); per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        pagination = query.order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify(items=[tx_json(t) for t in pagination.items], total=pagination.total, page=page, pages=pagination.pages)

    def tx_json(t): return {"id": t.id, "kind": t.kind, "title": t.title, "category": t.category, "amount": str(t.amount), "occurred_on": t.occurred_on.isoformat(), "notes": t.notes}

    @app.post("/api/transactions")
    @profiled
    def create_transaction():
        tx, error = validate_transaction(request.get_json(silent=True) or {})
        if error: return json_error(error, 400)
        row = Transaction(owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id, **tx)
        db.session.add(row); db.session.commit()
        return jsonify(tx_json(row)), 201

    @app.patch("/api/transactions/<int:txid>")
    @profiled
    def edit_transaction(txid):
        row = Transaction.query.filter_by(id=txid, owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id).first()
        if not row: return json_error("Transaction not found.", 404)
        tx, error = validate_transaction(request.get_json(silent=True) or {}, partial=True)
        if error: return json_error(error, 400)
        for key, value in tx.items(): setattr(row, key, value)
        db.session.commit(); return jsonify(tx_json(row))

    @app.delete("/api/transactions/<int:txid>")
    @profiled
    def delete_transaction(txid):
        row = Transaction.query.filter_by(id=txid, owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id).first()
        if not row: return json_error("Transaction not found.", 404)
        db.session.delete(row); db.session.commit(); return "", 204

    def validate_transaction(body, partial=False):
        allowed = {"kind", "title", "category", "amount", "occurred_on", "notes"}
        if set(body) - allowed: return None, "Unknown transaction field."
        result = {}
        required = ["kind", "title", "category", "amount", "occurred_on"]
        if not partial and any(not body.get(k) for k in required): return None, "Complete all required fields."
        for key in ("kind", "title", "category", "amount", "occurred_on", "notes"):
            if key not in body: continue
            value = body[key]
            if key == "kind" and value not in ("income", "expense"): return None, "Kind must be income or expense."
            if key in ("title", "category"):
                value = str(value).strip()
                if not value or len(value) > (200 if key == "title" else 80): return None, f"Invalid {key}."
            if key == "amount":
                try: value = Decimal(str(value)).quantize(Decimal("0.01"))
                except InvalidOperation: return None, "Amount must be a valid positive number."
                if not value.is_finite() or value <= 0: return None, "Amount must be greater than zero."
            if key == "occurred_on":
                try: value = date.fromisoformat(str(value))
                except ValueError: return None, "Date must use YYYY-MM-DD format."
            if key == "notes": value = str(value)[:2000]
            result[key] = value
        return result, None

    @app.get("/api/dashboard")
    @profiled
    def dashboard():
        try: start, end = parse_period()
        except ValueError as e: return json_error(str(e), 400)
        rows = Transaction.query.filter_by(owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id).filter(Transaction.occurred_on >= start, Transaction.occurred_on <= end).all()
        income = sum((r.amount for r in rows if r.kind == "income"), Decimal("0.00"))
        expenses = sum((r.amount for r in rows if r.kind == "expense"), Decimal("0.00"))
        rate = ((income-expenses)/income*100).quantize(Decimal("0.1")) if income else None
        month = start.strftime("%Y-%m")
        budgets = Budget.query.filter_by(owner_id=g.user.id, family_id=g.membership.family_id, month=month).all()
        spent_by_category = {}
        for r in rows:
            if r.kind == "expense": spent_by_category[r.category] = spent_by_category.get(r.category, Decimal("0")) + r.amount
        budget_total = sum((b.amount for b in budgets if b.category == "Overall"), Decimal("0"))
        if not budget_total: budget_total = sum((b.amount for b in budgets), Decimal("0"))
        utilization = (expenses / budget_total * 100).quantize(Decimal("0.1")) if budget_total else None
        categories = db.session.query(Transaction.category, func.sum(Transaction.amount)).filter_by(owner_id=g.user.id, family_id=g.membership.family_id, profile_id=g.profile.id, kind="expense").filter(Transaction.occurred_on >= start, Transaction.occurred_on <= end).group_by(Transaction.category).all()
        daily = {}
        for row in rows:
            point = daily.setdefault(row.occurred_on.isoformat(), {"date": row.occurred_on.isoformat(), "income": Decimal("0"), "expenses": Decimal("0")})
            point[row.kind if row.kind == "income" else "expenses"] += row.amount
        trend = [{**point, "income": str(point["income"]), "expenses": str(point["expenses"])} for point in sorted(daily.values(), key=lambda x: x["date"])]
        return jsonify(period={"start":start.isoformat(), "end":end.isoformat()}, income=str(income), expenses=str(expenses), balance=str(income-expenses), savings_rate=str(rate) if rate is not None else None, budget_utilization=str(utilization) if utilization is not None else None, categories=[{"category":c, "amount":str(a)} for c,a in categories], trend=trend)

    @app.get("/api/budgets")
    @profiled
    def list_budgets():
        month = request.args.get("month", date.today().strftime("%Y-%m"))
        rows = Budget.query.filter_by(owner_id=g.user.id, family_id=g.membership.family_id, month=month).all()
        return jsonify(items=[{"id":b.id,"category":b.category,"amount":str(b.amount),"month":b.month} for b in rows])

    @app.post("/api/budgets")
    @profiled
    def upsert_budget():
        body = request.get_json(silent=True) or {}
        category = str(body.get("category", "Overall")).strip()
        month = str(body.get("month", date.today().strftime("%Y-%m")))
        try: amount = Decimal(str(body.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError): return json_error("Enter a valid budget amount.", 400)
        if amount <= 0 or len(category) > 80 or len(month) != 7: return json_error("Enter a positive amount, category and YYYY-MM month.", 400)
        row = Budget.query.filter_by(owner_id=g.user.id, category=category, month=month).first()
        if row: row.amount = amount
        else: row = Budget(owner_id=g.user.id, family_id=g.membership.family_id, category=category, amount=amount, month=month); db.session.add(row)
        db.session.commit(); return jsonify(id=row.id, category=row.category, amount=str(row.amount), month=row.month), 201

    @app.get("/api/family/members")
    @authenticated
    def family_members():
        if not g.profile or g.profile.role != "admin": return json_error("Administrator profile required.", 403)
        profiles = FamilyProfile.query.filter_by(owner_user_id=g.user.id, family_id=g.membership.family_id).order_by(FamilyProfile.id).all()
        return jsonify(items=[{"name":p.display_name,"role":p.role} for p in profiles])

    @app.get("/api/family/overview")
    @profiled
    def family_overview():
        if g.profile.role != "admin": return json_error("Administrator profile required.", 403)
        try: start, end = parse_period()
        except ValueError as e: return json_error(str(e), 400)
        profiles = FamilyProfile.query.filter_by(owner_user_id=g.user.id, family_id=g.membership.family_id).order_by(FamilyProfile.id).all()
        report = []
        household_income = Decimal("0.00"); household_expenses = Decimal("0.00")
        for p in profiles:
            rows = Transaction.query.filter_by(owner_id=g.user.id, family_id=g.membership.family_id, profile_id=p.id).filter(Transaction.occurred_on >= start, Transaction.occurred_on <= end).all()
            income = sum((r.amount for r in rows if r.kind == "income"), Decimal("0.00"))
            expenses = sum((r.amount for r in rows if r.kind == "expense"), Decimal("0.00"))
            household_income += income; household_expenses += expenses
            report.append({"profile_id":p.id,"name":p.display_name,"role":p.role,"income":str(income),"expenses":str(expenses),"balance":str(income-expenses),"transactions":[tx_json(r) for r in rows]})
        return jsonify(period={"start":start.isoformat(),"end":end.isoformat()},income=str(household_income),expenses=str(household_expenses),balance=str(household_income-household_expenses),members=report)

    with app.app_context():
        db.create_all()
        # Additive upgrade for a workspace database created before profile support.
        if "profile_id" not in {column["name"] for column in inspect(db.engine).get_columns("transaction")}:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE "transaction" ADD COLUMN profile_id INTEGER REFERENCES family_profiles(id)'))
        with db.engine.begin() as connection:
            connection.execute(text('CREATE INDEX IF NOT EXISTS ix_transaction_profile_id ON "transaction" (profile_id)'))
    return app

app = create_app()
if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5001")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )

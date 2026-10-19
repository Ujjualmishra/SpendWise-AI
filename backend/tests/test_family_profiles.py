from app import create_app


def make_client():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SESSION_COOKIE_SECURE": False,
    })
    return app.test_client()


def create_account(client):
    response = client.post("/api/auth/signup", json={
        "name": "Asha Admin",
        "email": "asha@example.test",
        "password": "long-test-password",
        "family_name": "Sharma Family",
    })
    assert response.status_code == 201


def select(client, profile_id, pin):
    return client.post("/api/profiles/select", json={"profile_id": profile_id, "pin": pin})


def test_profiles_keep_transactions_private_and_admin_can_review_family():
    client = make_client()
    create_account(client)
    admin_profile = client.get("/api/profiles").json["items"][0]
    assert admin_profile["role"] == "admin"
    assert select(client, admin_profile["id"], "2468").status_code == 200

    add_member = client.post("/api/profiles", json={"name": "Ravi"})
    assert add_member.status_code == 201
    member_id = add_member.json["id"]

    admin_tx = client.post("/api/transactions", json={
        "kind": "expense", "title": "Rent", "category": "Housing",
        "amount": "12000.00", "occurred_on": "2026-10-01",
    })
    assert admin_tx.status_code == 201

    assert client.post("/api/profiles/lock").status_code == 204
    assert select(client, member_id, "1357").status_code == 200
    member_tx = client.post("/api/transactions", json={
        "kind": "income", "title": "Allowance", "category": "Allowance",
        "amount": "500.00", "occurred_on": "2026-10-02",
    })
    assert member_tx.status_code == 201

    # Member sees their own records but cannot read or aggregate other profiles.
    assert client.get("/api/transactions?start=2026-10-01&end=2026-10-31").json["total"] == 1
    assert client.patch(f"/api/transactions/{admin_tx.json['id']}", json={"title": "Changed"}).status_code == 404
    assert client.get("/api/family/overview?start=2026-10-01&end=2026-10-31").status_code == 403

    # Admin can see both profiles in the household summary.
    assert client.post("/api/profiles/lock").status_code == 204
    assert select(client, admin_profile["id"], "2468").status_code == 200
    overview = client.get("/api/family/overview?start=2026-10-01&end=2026-10-31")
    assert overview.status_code == 200
    assert overview.json["income"] == "500.00"
    assert overview.json["expenses"] == "12000.00"
    assert len(overview.json["members"]) == 2


def test_profile_pin_is_required_after_it_is_set():
    client = make_client()
    create_account(client)
    profile = client.get("/api/profiles").json["items"][0]
    assert select(client, profile["id"], "2468").status_code == 200
    client.post("/api/profiles/lock")
    assert select(client, profile["id"], "9999").status_code == 401


def test_account_admin_can_reset_a_forgotten_profile_pin():
    client = make_client()
    create_account(client)
    profile = client.get("/api/profiles").json["items"][0]
    assert select(client, profile["id"], "2468").status_code == 200
    client.post("/api/profiles/lock")
    reset = client.post("/api/profiles/reset-pin", json={
        "profile_id": profile["id"],
        "account_password": "long-test-password",
        "new_pin": "8642",
    })
    assert reset.status_code == 200
    assert select(client, profile["id"], "2468").status_code == 401
    assert select(client, profile["id"], "8642").status_code == 200

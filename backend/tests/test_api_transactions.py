import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Transaction
from tests.helpers import IBAN_A, IBAN_B, World

TX = "/api/transactions"


def _account(client: TestClient, name: str = "Giro", **extra: Any) -> str:
    response = client.post("/api/accounts", json={"name": name, "kind": "giro", **extra})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _category(client: TestClient, name: str, parent_id: str | None = None) -> str:
    body: dict[str, Any] = {"name": name, "kind": "expense"}
    if parent_id:
        body["parent_id"] = parent_id
    response = client.post("/api/categories", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _tx(
    client: TestClient, account_id: str, amount: int, date: str = "2026-03-01", **extra: Any
) -> dict[str, Any]:
    response = client.post(
        TX, json={"account_id": account_id, "booking_date": date, "amount_cents": amount, **extra}
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _ids(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# ---------------------------------------------------------------- create


def test_create_manual_transaction(world: World) -> None:
    account = _account(world.owner)
    tag = world.owner.post("/api/tags", json={"name": "Urlaub"}).json()

    created = _tx(
        world.member,
        account,
        -1999,
        counterparty_name=" REWE ",
        counterparty_iban="de89 3704 0044 0532 0130 00",
        purpose="Einkauf",
        booking_text="Lastschrift",
        note="wichtig",
        tag_ids=[tag["id"]],
    )

    assert created["amount_cents"] == -1999 and created["currency"] == "EUR"
    assert created["counterparty_name"] == "REWE" and created["counterparty_iban"] == IBAN_A
    assert created["tags"] == [tag] and created["splits"] == []
    assert (created["category_id"], created["category_source"], created["is_transfer"]) == (None, None, False)
    assert created["raw"] is None and created["import_run_id"] is None
    assert world.owner.get(f"{TX}/{created['id']}").json()["id"] == created["id"]


def test_create_with_category_is_manual_and_without_applies_rules(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    fun = _category(world.owner, "Freizeit")
    world.owner.post(
        "/api/rules", json={"category_id": food, "conditions": {"counterparty_contains": "rewe"}}
    )

    ruled = _tx(world.owner, account, -100, counterparty_name="REWE Markt")
    manual = _tx(world.owner, account, -100, counterparty_name="REWE Markt", category_id=fun)
    plain = _tx(world.owner, account, -100, counterparty_name="Kino")

    assert (ruled["category_id"], ruled["category_source"]) == (food, "rule") and ruled["rule_id"]
    assert (manual["category_id"], manual["category_source"], manual["rule_id"]) == (fun, "manual", None)
    assert plain["category_id"] is None


def test_create_detects_transfers(world: World) -> None:
    giro = _account(world.owner, "Giro", iban=IBAN_A)
    savings = _account(world.owner, "Sparen", iban=IBAN_B)
    out = _tx(world.owner, giro, -5000, "2026-03-01", counterparty_iban=IBAN_B)
    assert out["transfer_peer_id"] is None

    incoming = _tx(world.owner, savings, 5000, "2026-03-02")

    assert incoming["transfer_peer_id"] == out["id"] and incoming["is_transfer"] is True
    assert world.owner.get(f"{TX}/{out['id']}").json()["transfer_peer_id"] == incoming["id"]


def test_create_validation(world: World) -> None:
    account = _account(world.owner)
    base = {"account_id": account, "booking_date": "2026-03-01", "amount_cents": -100}

    for patch in (
        {"amount_cents": 0},
        {"amount_cents": 10**15},
        {"amount_cents": 1.5},
        {"booking_date": "01.03.2026"},
        {"counterparty_iban": "DE89370400440532013001"},
        {"booking_text": "x" * 101},
        {"tag_ids": "nope"},
    ):
        assert world.owner.post(TX, json={**base, **patch}).status_code == 422, patch
    assert world.owner.post(TX, json={"booking_date": "2026-03-01", "amount_cents": 1}).status_code == 422
    assert world.owner.post(TX, json={**base, "category_id": str(uuid.uuid4())}).status_code == 404
    assert world.owner.post(TX, json={**base, "tag_ids": [str(uuid.uuid4())]}).status_code == 404
    assert world.owner.post(TX, json={**base, "account_id": str(uuid.uuid4())}).status_code == 404


# ---------------------------------------------------------------- list


def test_list_orders_paginates_and_omits_raw(world: World) -> None:
    account = _account(world.owner)
    older = _tx(world.owner, account, -1, "2026-01-01")
    newest = _tx(world.owner, account, -2, "2026-03-01")
    middle = _tx(world.owner, account, -3, "2026-02-01")

    body = world.owner.get(TX).json()
    assert [i["id"] for i in body["items"]] == [newest["id"], middle["id"], older["id"]]
    assert body["total"] == 3 and "raw" not in body["items"][0]
    assert {"splits", "tags", "is_transfer", "category_source"} <= set(body["items"][0])

    page = world.owner.get(TX, params={"limit": 1, "offset": 1}).json()
    assert [i["id"] for i in page["items"]] == [middle["id"]] and page["total"] == 3
    assert world.owner.get(TX, params={"limit": 201}).status_code == 422
    assert world.owner.get(TX, params={"limit": 0}).status_code == 422
    assert world.owner.get(TX, params={"offset": -1}).status_code == 422
    assert world.owner.get(TX, params={"offset": 50}).json() == {"items": [], "total": 3}


def test_list_ties_on_booking_date_are_stable(world: World) -> None:
    account = _account(world.owner)
    created = [_tx(world.owner, account, -n, "2026-03-01")["id"] for n in range(1, 6)]

    first = _ids(world.owner.get(TX))
    assert sorted(first) == sorted(created)
    assert first == _ids(world.owner.get(TX))
    paged = _ids(world.owner.get(TX, params={"limit": 2})) + _ids(
        world.owner.get(TX, params={"limit": 3, "offset": 2})
    )
    assert paged == first


def test_uncategorized_filter_skips_paired_transfers(world: World) -> None:
    giro = _account(world.owner, "Giro")
    savings = _account(world.owner, "Tagesgeld")
    out = _tx(world.owner, giro, -5000, "2026-03-01")
    into = _tx(world.owner, savings, 5000, "2026-03-01")
    loose = _tx(world.owner, giro, -700, "2026-03-02")
    paired = world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": into["id"]})
    assert paired.status_code == 200, paired.text

    listed = set(_ids(world.owner.get(TX, params={"uncategorized": "true"})))
    assert listed == {loose["id"]}
    assert world.owner.get("/api/dashboard", params={"month": "2026-03"}).json()["uncategorized_count"] == 1


def test_list_filters(world: World) -> None:
    giro = _account(world.owner, "Giro")
    card = _account(world.owner, "Karte")
    food = _category(world.owner, "Lebensmittel")
    bakery = _category(world.owner, "Bäckerei", food)
    fun = _category(world.owner, "Freizeit")
    tag = world.owner.post("/api/tags", json={"name": "Urlaub"}).json()
    a = _tx(world.owner, giro, -1000, "2026-03-01", counterparty_name="REWE", category_id=food)
    b = _tx(
        world.owner,
        giro,
        -2500,
        "2026-03-05",
        counterparty_name="Bäcker",
        category_id=bakery,
        tag_ids=[tag["id"]],
    )
    c = _tx(world.owner, card, 40000, "2026-03-10", purpose="Gehalt März", category_id=fun)
    d = _tx(world.owner, card, -300, "2026-04-01", note="Bar bezahlt")

    def ids(**params: Any) -> set[str]:
        return set(_ids(world.owner.get(TX, params=params)))

    assert ids(account_id=[giro]) == {a["id"], b["id"]}
    assert ids(account_id=[giro, card]) == {a["id"], b["id"], c["id"], d["id"]}
    assert ids(category_id=[food]) == {a["id"], b["id"]}  # a top-level category includes its children
    assert ids(category_id=[bakery]) == {b["id"]}
    assert ids(category_id=[bakery, fun]) == {b["id"], c["id"]}
    assert ids(uncategorized="true") == {d["id"]}
    assert ids(date_from="2026-03-05", date_to="2026-03-10") == {b["id"], c["id"]}
    assert ids(date_to="2026-03-01") == {a["id"]}
    assert ids(direction="in") == {c["id"]}
    assert ids(direction="out") == {a["id"], b["id"], d["id"]}
    assert ids(amount_min=-2500, amount_max=-1000) == {a["id"], b["id"]}
    assert ids(amount_min=0) == {c["id"]}
    assert ids(tag_id=tag["id"]) == {b["id"]}
    assert ids(tag_id=str(uuid.uuid4())) == set()
    assert ids(q="rewe") == {a["id"]}
    assert ids(q="gehalt") == {c["id"]}
    assert ids(q="BAR BEZ") == {d["id"]}
    assert ids(q="bäck", account_id=[giro], direction="out") == {b["id"]}
    assert world.owner.get(TX, params={"direction": "sideways"}).status_code == 422
    assert world.owner.get(TX, params={"date_from": "heute"}).status_code == 422
    assert world.owner.get(TX, params={"account_id": "x"}).status_code == 422


def test_list_search_escapes_wildcards(world: World) -> None:
    account = _account(world.owner)
    percent = _tx(world.owner, account, -1, purpose="Rabatt 100% sicher")
    underscore = _tx(world.owner, account, -1, purpose="ab_cd")
    backslash = _tx(world.owner, account, -1, purpose=r"pfad\ordner")
    plain = _tx(world.owner, account, -1, purpose="abxcd 100 mal")

    def found(q: str) -> set[str]:
        return set(_ids(world.owner.get(TX, params={"q": q})))

    assert found("100%") == {percent["id"]}
    assert found("%") == {percent["id"]}
    assert found("b_c") == {underscore["id"]}
    assert found("_") == {underscore["id"]}
    assert found("\\") == {backslash["id"]}
    assert found("xcd") == {plain["id"]}
    assert world.owner.get(TX, params={"q": "x" * 201}).status_code == 422


def test_list_transfer_modes(world: World) -> None:
    giro = _account(world.owner, "Giro", iban=IBAN_A)
    savings = _account(world.owner, "Sparen", iban=IBAN_B)
    transfer_top = world.owner.post("/api/categories", json={"name": "Umbuchung", "kind": "transfer"}).json()[
        "id"
    ]
    paired_out = _tx(world.owner, giro, -100, counterparty_iban=IBAN_B)
    paired_in = _tx(world.owner, savings, 100)
    by_category = _tx(world.owner, giro, -50, category_id=transfer_top)
    normal = _tx(world.owner, giro, -10)

    def ids(mode: str | None) -> set[str]:
        params = {"transfers": mode} if mode else {}
        return set(_ids(world.owner.get(TX, params=params)))

    everything = {paired_out["id"], paired_in["id"], by_category["id"], normal["id"]}
    assert ids(None) == ids("include") == everything
    assert ids("exclude") == {normal["id"]}
    assert ids("only") == {paired_out["id"], paired_in["id"], by_category["id"]}
    assert world.owner.get(TX, params={"transfers": "maybe"}).status_code == 422


# ---------------------------------------------------------------- update


def test_patch_sets_manual_category_note_and_tags(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    other = _category(world.owner, "Sonstiges")
    one = world.owner.post("/api/tags", json={"name": "A"}).json()
    two = world.owner.post("/api/tags", json={"name": "B"}).json()
    world.owner.post(
        "/api/rules", json={"category_id": other, "conditions": {"counterparty_contains": "rewe"}}
    )
    tx = _tx(world.owner, account, -100, counterparty_name="REWE")
    assert tx["category_source"] == "rule"

    patched = world.member.patch(
        f"{TX}/{tx['id']}",
        json={"category_id": food, "note": "Notiz", "tag_ids": [two["id"], one["id"]], "learn": False},
    ).json()

    assert (patched["category_id"], patched["category_source"], patched["rule_id"]) == (food, "manual", None)
    assert patched["note"] == "Notiz" and patched["tags"] == [one, two]  # sorted by name
    assert patched["similar_updated"] == 0 and patched["raw"] is None

    replaced = world.owner.patch(f"{TX}/{tx['id']}", json={"tag_ids": [one["id"]]}).json()
    assert replaced["tags"] == [one] and replaced["category_id"] == food  # category untouched when absent
    cleared = world.owner.patch(
        f"{TX}/{tx['id']}", json={"tag_ids": [], "note": None, "category_id": None}
    ).json()
    assert (cleared["tags"], cleared["note"]) == ([], None)
    assert (cleared["category_id"], cleared["category_source"], cleared["rule_id"]) == (None, None, None)


def test_patch_validation(world: World) -> None:
    account = _account(world.owner)
    tx = _tx(world.owner, account, -100)
    url = f"{TX}/{tx['id']}"

    assert world.owner.patch(url, json={"category_id": str(uuid.uuid4())}).status_code == 404
    assert world.owner.patch(url, json={"tag_ids": [str(uuid.uuid4())]}).status_code == 404
    assert world.owner.patch(url, json={"category_id": "nope"}).status_code == 422
    assert world.owner.patch(url, json={"learn": "maybe"}).status_code == 422
    assert world.owner.patch(url, json={}).status_code == 200


def test_patch_learns_a_rule_and_can_apply_it_to_similar(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    fun = _category(world.owner, "Freizeit")
    source = _tx(world.owner, account, -100, counterparty_name="REWE Markt")
    twin = _tx(world.owner, account, -500, counterparty_name="REWE  MARKT Filiale 7")
    similar = _tx(world.owner, account, -200, counterparty_name="rewe city")
    manual = _tx(world.owner, account, -300, counterparty_name="REWE Markt", category_id=fun)
    unrelated = _tx(world.owner, account, -400, counterparty_name="Kino")

    patched = world.owner.patch(
        f"{TX}/{source['id']}", json={"category_id": food, "apply_to_similar": True}
    ).json()

    # The learned condition is the normalized counterparty "rewe markt"; "rewe city" does not contain it.
    assert patched["similar_updated"] == 1
    rules = world.owner.get("/api/rules").json()
    assert [(r["source"], r["conditions"], r["category_id"]) for r in rules] == [
        ("learned", {"counterparty_contains": "rewe markt"}, food)
    ]
    twin_after = world.owner.get(f"{TX}/{twin['id']}").json()
    assert (twin_after["category_id"], twin_after["category_source"], twin_after["rule_id"]) == (
        food,
        "rule",
        rules[0]["id"],
    )
    assert world.owner.get(f"{TX}/{similar['id']}").json()["category_id"] is None
    assert world.owner.get(f"{TX}/{manual['id']}").json()["category_id"] == fun
    assert world.owner.get(f"{TX}/{unrelated['id']}").json()["category_id"] is None

    # Repeating the correction upserts the rule and has nothing left to update.
    again = world.owner.patch(
        f"{TX}/{source['id']}", json={"category_id": food, "apply_to_similar": True}
    ).json()
    assert again["similar_updated"] == 0
    assert len(world.owner.get("/api/rules").json()) == 1


def test_patch_with_iban_learns_by_iban_and_learn_can_be_disabled(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    tx = _tx(world.owner, account, -100, counterparty_name="REWE", counterparty_iban=IBAN_B)
    other = _tx(world.owner, account, -100, counterparty_name="Anders", counterparty_iban=IBAN_B)

    world.owner.patch(
        f"{TX}/{tx['id']}", json={"category_id": food, "learn": False, "apply_to_similar": True}
    )
    assert world.owner.get("/api/rules").json() == []

    result = world.owner.patch(
        f"{TX}/{tx['id']}", json={"category_id": food, "apply_to_similar": True}
    ).json()
    assert result["similar_updated"] == 1
    assert world.owner.get("/api/rules").json()[0]["conditions"] == {"counterparty_iban": IBAN_B}
    assert world.owner.get(f"{TX}/{other['id']}").json()["category_id"] == food


# ---------------------------------------------------------------- splits


def test_splits_replace_and_clear(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    fun = _category(world.owner, "Freizeit")
    tx = _tx(world.owner, account, -3000)
    url = f"{TX}/{tx['id']}/splits"

    done = world.member.put(
        url,
        json=[
            {"amount_cents": -1000, "category_id": food, "note": "Obst"},
            {"amount_cents": -2000, "category_id": fun},
        ],
    )
    assert done.status_code == 200, done.text
    splits = done.json()["splits"]
    assert [(s["position"], s["amount_cents"], s["category_id"], s["note"]) for s in splits] == [
        (0, -1000, food, "Obst"),
        (1, -2000, fun, None),
    ]
    again = world.owner.put(url, json=[{"amount_cents": -500}, {"amount_cents": -2500}]).json()
    assert [s["amount_cents"] for s in again["splits"]] == [-500, -2500]
    assert [s["amount_cents"] for s in world.owner.get(f"{TX}/{tx['id']}").json()["splits"]] == [-500, -2500]
    listed = world.owner.get(TX).json()["items"][0]
    assert len(listed["splits"]) == 2

    assert world.owner.put(url, json=[]).json()["splits"] == []


def test_splits_validation(world: World) -> None:
    account = _account(world.owner)
    tx = _tx(world.owner, account, -3000)
    url = f"{TX}/{tx['id']}/splits"

    assert world.owner.put(url, json=[{"amount_cents": -1000}, {"amount_cents": -1000}]).status_code == 422
    assert world.owner.put(url, json=[{"amount_cents": -3000}]).status_code == 422
    assert world.owner.put(url, json=[{"amount_cents": -1}] * 51).status_code == 422
    assert world.owner.put(url, json={"amount_cents": -3000}).status_code == 422
    assert world.owner.put(url, json=[{"amount_cents": "x"}, {"amount_cents": 1}]).status_code == 422
    unknown = [{"amount_cents": -1000, "category_id": str(uuid.uuid4())}, {"amount_cents": -2000}]
    assert world.owner.put(url, json=unknown).status_code == 404
    assert world.owner.get(f"{TX}/{tx['id']}").json()["splits"] == []


def test_split_category_matches_list_filter(world: World) -> None:
    account = _account(world.owner)
    food = _category(world.owner, "Lebensmittel")
    other = _category(world.owner, "Sonstiges")
    tx = _tx(world.owner, account, -3000, category_id=other)
    world.owner.put(
        f"{TX}/{tx['id']}/splits",
        json=[{"amount_cents": -1000, "category_id": food}, {"amount_cents": -2000}],
    )

    assert _ids(world.owner.get(TX, params={"category_id": [food]})) == [tx["id"]]
    assert (
        _ids(world.owner.get(TX, params={"category_id": [other]})) == []
    )  # the split replaces the parent category
    assert _ids(world.owner.get(TX, params={"uncategorized": "true"})) == []


# ---------------------------------------------------------------- delete and transfers


def test_delete_transaction(world: World) -> None:
    account = _account(world.owner)
    tx = _tx(world.owner, account, -100)

    assert world.member.delete(f"{TX}/{tx['id']}").status_code == 204
    assert world.owner.get(f"{TX}/{tx['id']}").status_code == 404
    assert world.owner.delete(f"{TX}/{tx['id']}").status_code == 404
    assert world.owner.get(TX).json() == {"items": [], "total": 0}


def test_manual_transfer_pairing_and_candidates(world: World) -> None:
    a = _account(world.owner, "A")
    b = _account(world.owner, "B")
    out = _tx(world.owner, a, -1000, "2026-03-01")
    near = _tx(world.owner, b, 1000, "2026-03-06")
    far = _tx(world.owner, b, 1000, "2026-03-07")
    wrong_amount = _tx(world.owner, b, 999, "2026-03-01")
    same_account = _tx(world.owner, a, 1000, "2026-03-01")

    candidates = world.owner.get(f"{TX}/{out['id']}/transfer-candidates")
    assert [c["id"] for c in candidates.json()] == [near["id"]]
    assert far["id"] not in str(candidates.json()) and wrong_amount["id"] not in str(candidates.json())

    assert (
        world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": same_account["id"]}).status_code
        == 422
    )
    assert (
        world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": wrong_amount["id"]}).status_code
        == 422
    )
    assert world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": out["id"]}).status_code == 422
    assert (
        world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": str(uuid.uuid4())}).status_code == 404
    )

    paired = world.member.post(f"{TX}/{out['id']}/transfer", json={"peer_id": near["id"]})
    assert paired.status_code == 200
    assert paired.json()["transfer_peer_id"] == near["id"] and paired.json()["is_transfer"] is True
    assert world.owner.get(f"{TX}/{near['id']}").json()["transfer_peer_id"] == out["id"]
    assert world.owner.get(f"{TX}/{out['id']}/transfer-candidates").json() == []
    assert world.owner.post(f"{TX}/{out['id']}/transfer", json={"peer_id": far["id"]}).status_code == 409

    assert world.owner.delete(f"{TX}/{near['id']}/transfer").status_code == 204
    assert world.owner.get(f"{TX}/{out['id']}").json()["transfer_peer_id"] is None
    assert world.owner.delete(f"{TX}/{near['id']}/transfer").status_code == 404
    assert world.owner.get(f"{TX}/{out['id']}").json()["is_transfer"] is False


# ---------------------------------------------------------------- visibility and isolation


def test_private_account_transactions_are_invisible_to_other_members(world: World, db: Session) -> None:
    shared = _account(world.owner, "Gemeinsam", iban=IBAN_A)
    private = _account(world.owner, "Privat", visibility="private", iban=IBAN_B)
    food = _category(world.owner, "Lebensmittel")
    visible = _tx(world.owner, shared, -1000, "2026-03-01", counterparty_iban=IBAN_B)
    hidden = _tx(world.owner, private, 1000, "2026-03-01", counterparty_name="Geheim")
    # Detection ran as the owner, who can see both accounts, so the pair exists. The partner sees a flag only.
    assert hidden["transfer_peer_id"] == visible["id"]

    listing = world.member.get(TX).json()
    assert [i["id"] for i in listing["items"]] == [visible["id"]] and listing["total"] == 1
    assert listing["items"][0]["transfer_peer_id"] is None and listing["items"][0]["is_transfer"] is True
    assert world.owner.get(f"{TX}/{visible['id']}").json()["transfer_peer_id"] == hidden["id"]
    assert world.member.get(f"{TX}/{visible['id']}").json()["transfer_peer_id"] is None
    assert world.member.get(TX, params={"account_id": [private]}).json() == {"items": [], "total": 0}
    assert world.member.get(TX, params={"q": "geheim"}).json() == {"items": [], "total": 0}

    url = f"{TX}/{hidden['id']}"
    assert world.member.get(url).status_code == 404
    assert world.member.patch(url, json={"category_id": food}).status_code == 404
    assert world.member.put(f"{url}/splits", json=[]).status_code == 404
    assert world.member.delete(url).status_code == 404
    assert world.member.get(f"{url}/transfer-candidates").status_code == 404
    assert world.member.post(f"{url}/transfer", json={"peer_id": visible["id"]}).status_code == 404
    assert (
        world.member.post(f"{TX}/{visible['id']}/transfer", json={"peer_id": hidden["id"]}).status_code == 404
    )
    assert world.member.delete(f"{url}/transfer").status_code == 404
    # Unpairing from the visible side behaves as "not paired" for the partner, and nothing changed.
    assert world.member.delete(f"{TX}/{visible['id']}/transfer").status_code == 404
    assert world.owner.get(f"{TX}/{hidden['id']}").json()["transfer_peer_id"] == visible["id"]
    posted = world.member.post(
        TX, json={"account_id": private, "booking_date": "2026-03-01", "amount_cents": -1}
    )
    assert posted.status_code == 404
    db.expire_all()
    assert db.get(Transaction, uuid.UUID(hidden["id"])) is not None


def test_candidates_never_include_hidden_transactions(world: World) -> None:
    shared = _account(world.owner, "Gemeinsam")
    private = _account(world.owner, "Privat", visibility="private")
    other = _account(world.owner, "Sonstiges")
    out = _tx(world.owner, shared, -1000, "2026-03-01")
    hidden = _tx(world.owner, private, 1000, "2026-03-01")
    visible = _tx(world.owner, other, 1000, "2026-03-02")

    assert {c["id"] for c in world.owner.get(f"{TX}/{out['id']}/transfer-candidates").json()} == {
        hidden["id"],
        visible["id"],
    }
    assert [c["id"] for c in world.member.get(f"{TX}/{out['id']}/transfer-candidates").json()] == [
        visible["id"]
    ]


def test_automatic_transfer_detection_ignores_hidden_accounts(world: World) -> None:
    shared = _account(world.owner, "Gemeinsam", iban=IBAN_A)
    private = _account(world.owner, "Privat", visibility="private", iban=IBAN_B)
    _tx(world.owner, private, 1000, "2026-03-01")

    created = _tx(world.member, shared, -1000, "2026-03-01", counterparty_iban=IBAN_B)

    assert created["transfer_peer_id"] is None and created["is_transfer"] is False


def test_transactions_are_isolated_between_households(world: World) -> None:
    account = _account(world.owner)
    category = _category(world.owner, "Lebensmittel")
    tx = _tx(world.owner, account, -100, counterparty_name="REWE")
    url = f"{TX}/{tx['id']}"
    foreign_account = _account(world.stranger)
    foreign_tx = _tx(world.stranger, foreign_account, 100)

    assert world.stranger.get(TX, params={"account_id": [account]}).json() == {"items": [], "total": 0}
    assert _ids(world.stranger.get(TX)) == [foreign_tx["id"]]
    assert world.stranger.get(url).status_code == 404
    assert world.stranger.patch(url, json={"note": "x"}).status_code == 404
    assert world.stranger.put(f"{url}/splits", json=[]).status_code == 404
    assert world.stranger.delete(url).status_code == 404
    assert world.stranger.get(f"{url}/transfer-candidates").status_code == 404
    assert world.stranger.post(f"{url}/transfer", json={"peer_id": foreign_tx["id"]}).status_code == 404
    assert (
        world.stranger.post(f"{TX}/{foreign_tx['id']}/transfer", json={"peer_id": tx["id"]}).status_code
        == 404
    )
    assert world.stranger.delete(f"{url}/transfer").status_code == 404
    assert (
        world.stranger.post(
            TX, json={"account_id": account, "booking_date": "2026-03-01", "amount_cents": 1}
        ).status_code
        == 404
    )
    # Foreign categories and tags cannot be attached either.
    assert world.stranger.patch(f"{TX}/{foreign_tx['id']}", json={"category_id": category}).status_code == 404
    tag = world.owner.post("/api/tags", json={"name": "Privat"}).json()
    assert world.stranger.patch(f"{TX}/{foreign_tx['id']}", json={"tag_ids": [tag["id"]]}).status_code == 404
    assert world.stranger.get(TX, params={"tag_id": tag["id"]}).json() == {"items": [], "total": 0}
    assert world.owner.get(url).json()["note"] is None

"""Transfer detection, manual pairing and candidates against a real database."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.finance.transfers import detect_transfers, find_candidates, pair, unpair
from app.models import AccountVisibility, HouseholdRole
from tests.conftest import UserFactory
from tests.helpers import IBAN_A, IBAN_B, IBAN_C, IBAN_EXTERNAL, make_account, make_tx, member_of

DAY = date(2026, 2, 10)


def test_detect_pairs_a_unique_candidate_via_either_iban(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    giro = make_account(db, user, "Giro", iban=IBAN_A)
    savings = make_account(db, user, "Sparen", iban=IBAN_B)
    out = make_tx(db, giro, -50000, DAY, counterparty_iban=IBAN_B)
    incoming = make_tx(db, savings, 50000, date(2026, 2, 12))  # the savings side lists no IBAN

    assert detect_transfers(db, giro.household_id, [out, incoming]) == 1
    db.commit()

    assert out.transfer_peer_id == incoming.id and incoming.transfer_peer_id == out.id

    # The reverse direction works too: only the receiving side names the other account.
    other = make_tx(db, giro, -700, DAY)
    receiving = make_tx(db, savings, 700, DAY, counterparty_iban=IBAN_A)
    assert detect_transfers(db, giro.household_id, [other]) == 1
    assert other.transfer_peer_id == receiving.id


def test_detect_does_not_change_categories(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    giro = make_account(db, user, iban=IBAN_A)
    savings = make_account(db, user, "Sparen", iban=IBAN_B)
    out = make_tx(db, giro, -100, DAY, counterparty_iban=IBAN_B)
    make_tx(db, savings, 100, DAY)

    detect_transfers(db, giro.household_id, [out])

    assert out.category_id is None and out.category_source is None


def test_detect_ignores_ambiguous_candidates(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    giro = make_account(db, user, "Giro", iban=IBAN_A)
    savings = make_account(db, user, "Sparen", iban=IBAN_B)
    card = make_account(db, user, "Karte", iban=IBAN_C)
    out = make_tx(db, giro, -1000, DAY, counterparty_iban=IBAN_B)
    one = make_tx(db, savings, 1000, DAY)
    two = make_tx(db, savings, 1000, date(2026, 2, 11))

    assert detect_transfers(db, giro.household_id, [out]) == 0
    assert out.transfer_peer_id is None and one.transfer_peer_id is None

    # A candidate on another account that also names the IBAN makes it ambiguous as well.
    three = make_tx(db, card, 1000, DAY, counterparty_iban=IBAN_A)
    assert detect_transfers(db, giro.household_id, [out]) == 0
    assert (two.transfer_peer_id, three.transfer_peer_id) == (None, None)


def test_detect_requires_amount_window_iban_and_other_account(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    giro = make_account(db, user, "Giro", iban=IBAN_A)
    savings = make_account(db, user, "Sparen", iban=IBAN_B)
    out = make_tx(db, giro, -1000, DAY, counterparty_iban=IBAN_B)
    make_tx(db, savings, 1001, DAY)  # amount differs
    make_tx(db, savings, 1000, date(2026, 2, 14))  # four days away
    make_tx(db, giro, 1000, DAY, counterparty_iban=IBAN_B)  # same account
    assert detect_transfers(db, giro.household_id, [out]) == 0

    on_the_edge = make_tx(db, savings, 1000, date(2026, 2, 13))  # exactly three days
    assert detect_transfers(db, giro.household_id, [out]) == 1
    assert out.transfer_peer_id == on_the_edge.id

    # No IBAN link at all: same amounts alone never pair.
    unrelated = make_account(db, user, "Bar")
    lonely = make_tx(db, unrelated, -300, DAY)
    make_tx(db, savings, 300, DAY)
    assert detect_transfers(db, giro.household_id, [lonely]) == 0


def test_detect_leaves_paired_transactions_and_other_households_alone(
    db: Session, make_user: UserFactory
) -> None:
    user = make_user()
    stranger = make_user("stranger@example.com", household="Nachbarn")
    giro = make_account(db, user, iban=IBAN_A)
    savings = make_account(db, user, "Sparen", iban=IBAN_B)
    foreign = make_account(db, stranger, "Fremd", iban=IBAN_EXTERNAL)
    out = make_tx(db, giro, -1000, DAY, counterparty_iban=IBAN_EXTERNAL)
    make_tx(db, foreign, 1000, DAY)
    assert detect_transfers(db, giro.household_id, [out]) == 0

    peer = make_tx(db, savings, 1000, DAY, counterparty_iban=IBAN_A)
    out.counterparty_iban = IBAN_B
    db.commit()
    assert detect_transfers(db, giro.household_id, [out]) == 1
    assert detect_transfers(db, giro.household_id, [out, peer]) == 0  # already paired
    assert out.transfer_peer_id == peer.id


def test_detect_with_member_never_pairs_a_hidden_private_account(db: Session, make_user: UserFactory) -> None:
    owner = make_user()
    partner = make_user("partner@example.com", role=HouseholdRole.MEMBER)
    giro = make_account(db, owner, "Gemeinsam", iban=IBAN_A)
    secret = make_account(db, owner, "Privat", AccountVisibility.PRIVATE, iban=IBAN_B)
    out = make_tx(db, giro, -2000, DAY, counterparty_iban=IBAN_B)
    hidden = make_tx(db, secret, 2000, DAY)

    assert detect_transfers(db, giro.household_id, [out], member=member_of(partner)) == 0
    assert out.transfer_peer_id is None and hidden.transfer_peer_id is None

    # The owner sees both sides, and a hidden source transaction is skipped for the partner.
    assert detect_transfers(db, giro.household_id, [hidden], member=member_of(partner)) == 0
    assert detect_transfers(db, giro.household_id, [out], member=member_of(owner)) == 1


def test_manual_pair_and_unpair(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    member = member_of(user)
    a = make_tx(db, make_account(db, user, "A"), -1000, DAY)
    b = make_tx(db, make_account(db, user, "B"), 1000, date(2026, 3, 1))  # no window for manual pairing

    pair(db, member, a, b)
    db.commit()
    assert a.transfer_peer_id == b.id and b.transfer_peer_id == a.id

    unpair(db, member, b)
    db.commit()
    assert a.transfer_peer_id is None and b.transfer_peer_id is None
    with pytest.raises(HTTPException) as err:
        unpair(db, member, a)
    assert err.value.status_code == 404


def test_manual_pair_validation(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    member = member_of(user)
    first, second = make_account(db, user, "A"), make_account(db, user, "B")
    a = make_tx(db, first, -1000, DAY)
    same_account = make_tx(db, first, 1000, DAY)
    wrong_amount = make_tx(db, second, 999, DAY)
    b = make_tx(db, second, 1000, DAY)

    for other, status_code in ((same_account, 422), (wrong_amount, 422), (a, 422)):
        with pytest.raises(HTTPException) as err:
            pair(db, member, a, other)
        assert err.value.status_code == status_code

    pair(db, member, a, b)
    third = make_tx(db, second, 1000, DAY)
    with pytest.raises(HTTPException) as err:
        pair(db, member, a, third)
    assert err.value.status_code == 409


def test_manual_pair_and_candidates_respect_visibility(db: Session, make_user: UserFactory) -> None:
    owner = make_user()
    partner = make_user("partner@example.com", role=HouseholdRole.MEMBER)
    shared = make_account(db, owner, "Gemeinsam")
    secret = make_account(db, owner, "Privat", AccountVisibility.PRIVATE)
    out = make_tx(db, shared, -1000, DAY)
    hidden = make_tx(db, secret, 1000, DAY)
    visible = make_tx(db, make_account(db, owner, "Zweites"), 1000, date(2026, 2, 14))
    stranger = make_user("stranger@example.com", household="Nachbarn")
    make_tx(db, make_account(db, stranger, "Fremd"), 1000, DAY)

    with pytest.raises(HTTPException) as err:
        pair(db, member_of(partner), out, hidden)
    assert err.value.status_code == 404

    assert [c.id for c in find_candidates(db, member_of(partner), out)] == [visible.id]
    assert {c.id for c in find_candidates(db, member_of(owner), out)} == {hidden.id, visible.id}
    # Candidates are ordered by distance in days.
    assert find_candidates(db, member_of(owner), out)[0].id == hidden.id


def test_candidates_window_and_pairing_state(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    member = member_of(user)
    first, second = make_account(db, user, "A"), make_account(db, user, "B")
    tx = make_tx(db, first, -1000, DAY)
    near = make_tx(db, second, 1000, date(2026, 2, 15))
    make_tx(db, second, 1000, date(2026, 2, 16))  # six days
    make_tx(db, first, 1000, DAY)  # same account

    assert [c.id for c in find_candidates(db, member, tx)] == [near.id]

    pair(db, member, tx, near)
    assert find_candidates(db, member, tx) == []

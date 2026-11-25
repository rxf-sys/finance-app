"""Demo household with fictional data, for screenshots and trying the app locally.

The data goes through the same pipeline as real data: category rules, transfer pairs and
contract detection. Every name, IBAN and amount is invented. `seed_demo` refuses to run on
a database that already has users, so demo rows can never end up next to a real household.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.finance.contracts import add_interval, add_months_clamped, detect_contracts, today_berlin
from app.finance.dedupe import compute_dedupe_hash
from app.finance.default_categories import seed_default_categories
from app.finance.rules import RuleConditions, apply_rules
from app.models import (
    Account,
    AccountKind,
    AccountVisibility,
    AuditLog,
    Budget,
    Category,
    CategoryRule,
    Contract,
    ContractInterval,
    ContractKind,
    ContractPriceChange,
    ContractStatus,
    Household,
    HouseholdMember,
    HouseholdRole,
    RuleSource,
    SavingsContribution,
    SavingsGoal,
    Transaction,
    User,
)
from app.models.base import utcnow
from app.security.passwords import hash_password

DEMO_EMAIL = "demo@example.org"
DEMO_MEMBER_EMAIL = "sam@example.org"
MONTHS = 4

# Example IBANs from banking documentation, never real customer accounts.
IBAN_GIRO = "DE89370400440532013000"
IBAN_SAVINGS = "DE02120300000000202051"
IBAN_CARD = "DE02500105170137075030"
IBAN_POWER = "DE68210501700012345678"


class DemoRefusedError(Exception):
    """Raised when the database is not empty."""


@dataclass(frozen=True)
class DemoResult:
    household_id: uuid.UUID
    transactions: int
    contracts: int


@dataclass(frozen=True)
class _Recurring:
    counterparty: str
    iban: str
    purpose: str
    amount_cents: int
    day: int
    category: str


# (counterparty, rule category) for every counterparty the rules should recognise.
_RULES: tuple[tuple[str, str], ...] = (
    ("Musterfirma GmbH", "Gehalt"),
    ("Wohnbau Lindenhof", "Miete"),
    ("Stadtwerke Lindenhof", "Strom & Gas"),
    ("Glasfaser Nord", "Internet & Telefon"),
    ("Funkwerk Mobil", "Internet & Telefon"),
    ("Kinowelt Stream", "Streaming"),
    ("FitPoint Studio", "Sport"),
    ("Frischmarkt Lindenhof", "Supermarkt"),
    ("Bäckerei Korn", "Bäckerei"),
    ("Tankstelle am Ring", "Tanken"),
    ("Café Mühle", "Restaurant & Café"),
    ("Trattoria Lindenhof", "Restaurant & Café"),
    ("Drogerie Klar", "Drogerie"),
    ("Versandhaus Nord", "Haushalt"),
)

_FIXED: tuple[_Recurring, ...] = (
    _Recurring("Musterfirma GmbH", "DE75512108001245126199", "Lohn/Gehalt", 325_000, 1, "Gehalt"),
    _Recurring("Wohnbau Lindenhof eG", "DE91100000000123456789", "Miete Whg. 3 links", -105_000, 1, "Miete"),
    _Recurring("Stadtwerke Lindenhof", IBAN_POWER, "Abschlag Strom VK 400123", -8_600, 5, "Strom & Gas"),
    _Recurring(
        "Glasfaser Nord GmbH",
        "DE27100777770209299700",
        "Internet Kd-Nr. 77881",
        -3_999,
        10,
        "Internet & Telefon",
    ),
    _Recurring("Kinowelt Stream", "DE44500105175407324931", "Abo Monat", -1_399, 18, "Streaming"),
    _Recurring("FitPoint Studio", "DE60500105174429384513", "Mitgliedsbeitrag", -2_990, 3, "Sport"),
)
MOBILE = _Recurring(
    "Funkwerk Mobil", "DE31500105172637493512", "Mobilfunk Rechnung", -1_999, 15, "Internet & Telefon"
)
MOBILE_NEW_CENTS = -2_199


def _month_starts(today: date) -> list[date]:
    first = today.replace(day=1)
    return [add_months_clamped(first, -i) for i in range(MONTHS, -1, -1)]


class _Ledger:
    """Collects demo bookings with correct dedupe hashes."""

    def __init__(self, db: Session, household_id: uuid.UUID) -> None:
        self.db = db
        self.household_id = household_id
        self.created: list[Transaction] = []
        self._occurrences: dict[tuple[uuid.UUID, date, int, str], int] = {}

    def book(
        self, account: Account, day: date, cents: int, counterparty: str, iban: str | None, purpose: str
    ) -> Transaction:
        key = (account.id, day, cents, purpose)
        occurrence = self._occurrences.get(key, 0)
        self._occurrences[key] = occurrence + 1
        tx = Transaction(
            id=uuid.uuid4(),
            household_id=self.household_id,
            account_id=account.id,
            booking_date=day,
            value_date=day,
            amount_cents=cents,
            counterparty_name=counterparty,
            counterparty_iban=iban,
            purpose=purpose,
            booking_text="Gutschrift" if cents > 0 else "Lastschrift",
            dedupe_hash=compute_dedupe_hash(account.id, day, cents, iban, purpose, occurrence),
        )
        self.db.add(tx)
        self.created.append(tx)
        return tx


def _create_people(db: Session, password: str) -> tuple[Household, User]:
    household = Household(id=uuid.uuid4(), name="Musterhaushalt")
    owner = User(
        id=uuid.uuid4(),
        email=DEMO_EMAIL,
        display_name="Alex Muster",
        password_hash=hash_password(password),
        is_active=True,
        failed_login_count=0,
    )
    member = User(
        id=uuid.uuid4(),
        email=DEMO_MEMBER_EMAIL,
        display_name="Sam Muster",
        password_hash=None,
        is_active=True,
        failed_login_count=0,
    )
    db.add_all([household, owner, member])
    db.add(HouseholdMember(household=household, user=owner, role=HouseholdRole.OWNER, joined_at=utcnow()))
    db.add(HouseholdMember(household=household, user=member, role=HouseholdRole.MEMBER, joined_at=utcnow()))
    db.flush()
    return household, owner


def _create_accounts(
    db: Session, household_id: uuid.UUID, owner_id: uuid.UUID
) -> tuple[Account, Account, Account]:
    def account(
        name: str, kind: AccountKind, iban: str, opening: int, visibility: AccountVisibility
    ) -> Account:
        return Account(
            id=uuid.uuid4(),
            household_id=household_id,
            owner_user_id=owner_id,
            visibility=visibility,
            name=name,
            kind=kind,
            iban=iban,
            opening_balance_cents=opening,
        )

    giro = account("Girokonto", AccountKind.GIRO, IBAN_GIRO, 214_000, AccountVisibility.SHARED)
    savings = account("Tagesgeld", AccountKind.SAVINGS, IBAN_SAVINGS, 420_000, AccountVisibility.SHARED)
    card = account("Kreditkarte", AccountKind.CREDIT_CARD, IBAN_CARD, 0, AccountVisibility.PRIVATE)
    db.add_all([giro, savings, card])
    db.flush()
    return giro, savings, card


def _create_rules(
    db: Session, household_id: uuid.UUID, owner_id: uuid.UUID, categories: dict[str, Category]
) -> None:
    for counterparty, category in _RULES:
        db.add(
            CategoryRule(
                id=uuid.uuid4(),
                household_id=household_id,
                category_id=categories[category].id,
                conditions=RuleConditions(counterparty_contains=counterparty).to_json(),
                source=RuleSource.MANUAL,
                created_by_id=owner_id,
            )
        )


def _book_fixed(
    ledger: _Ledger, today: date, giro: Account, savings: Account, saving_category: Category
) -> None:
    starts = _month_starts(today)
    for index, start in enumerate(starts):
        last_month = index == len(starts) - 1
        month_label = start.strftime("%m/%Y")
        for item in (*_FIXED, MOBILE):
            day = start.replace(day=min(item.day, 28))
            if day > today:
                continue
            cents = MOBILE_NEW_CENTS if item is MOBILE and last_month else item.amount_cents
            ledger.book(giro, day, cents, item.counterparty, item.iban, f"{item.purpose} {month_label}")
        transfer_day = start.replace(day=2)
        if transfer_day <= today:
            out = ledger.book(
                giro, transfer_day, -30_000, "Alex Muster", IBAN_SAVINGS, f"Sparrate {month_label}"
            )
            inn = ledger.book(
                savings, transfer_day, 30_000, "Alex Muster", IBAN_GIRO, f"Sparrate {month_label}"
            )
            out.transfer_peer_id, inn.transfer_peer_id = inn.id, out.id
            out.category_id = inn.category_id = saving_category.id


def _book_everyday(ledger: _Ledger, today: date, giro: Account, card: Account, seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - varies demo amounts only, nothing security relevant
    day = _month_starts(today)[0]
    while day <= today:
        if day.weekday() == 5:
            ledger.book(
                giro, day, -rng.randint(4_200, 11_800), "Frischmarkt Lindenhof", None, "Einkauf Kartenzahlung"
            )
        if day.weekday() in (1, 4):
            ledger.book(giro, day, -rng.randint(380, 1_190), "Bäckerei Korn", None, "Kartenzahlung")
        if day.day in (7, 19):
            ledger.book(card, day, -rng.randint(5_200, 7_400), "Tankstelle am Ring", None, "Tankstelle")
        if day.day in (9, 23):
            place = "Café Mühle" if day.day == 9 else "Trattoria Lindenhof"
            ledger.book(card, day, -rng.randint(2_400, 6_800), place, None, "Bewirtung")
        if day.day in (12, 26):
            ledger.book(giro, day, -rng.randint(900, 3_200), "Drogerie Klar", None, "Kartenzahlung")
        if day.day == 21:
            ledger.book(card, day, -rng.randint(1_900, 8_900), "Versandhaus Nord", None, "Bestellung")
        day += timedelta(days=1)


def _review_contracts(db: Session, detected: list[Contract], ledger: _Ledger, today: date) -> int:
    """Confirm the real fixed costs, reject the rest, add a deadline and a price change; return the count."""
    fixed_ibans = {item.iban for item in (*_FIXED, MOBILE)}
    confirmed = 0
    for contract in detected:
        # Detection keys contracts by the counterparty IBAN; e.g. drugstore visits are rejected.
        if contract.counterparty_key not in fixed_ibans:
            contract.status = ContractStatus.IGNORED
            continue
        contract.status = ContractStatus.CONFIRMED
        contract.confirmed_at = utcnow()
        confirmed += 1
        if contract.counterparty_key == IBAN_POWER:
            contract.start_date = add_months_clamped(today, -23)
            contract.min_term_end = today + timedelta(days=24)
            contract.notice_period_days = 14
        if contract.counterparty_key == MOBILE.iban:
            contract.expected_amount_cents = MOBILE_NEW_CENTS
            last = max(
                (tx for tx in ledger.created if tx.counterparty_name == MOBILE.counterparty),
                key=lambda tx: tx.booking_date,
            )
            # The higher amount falls outside the detection band; link it like payment matching would.
            last.contract_id = contract.id
            contract.last_payment_date = last.booking_date
            contract.next_due_date = add_interval(last.booking_date, contract.interval)
            db.add(
                ContractPriceChange(
                    id=uuid.uuid4(),
                    contract_id=contract.id,
                    old_amount_cents=MOBILE.amount_cents,
                    new_amount_cents=MOBILE_NEW_CENTS,
                    effective_date=last.booking_date,
                    transaction_id=last.id,
                )
            )
    return confirmed


def _add_insurance(
    db: Session, household_id: uuid.UUID, giro: Account, category: Category, today: date
) -> None:
    db.add(
        Contract(
            id=uuid.uuid4(),
            household_id=household_id,
            account_id=giro.id,
            category_id=category.id,
            name="Lindenhof Versicherung Haftpflicht",
            kind=ContractKind.INSURANCE,
            status=ContractStatus.CONFIRMED,
            counterparty_key="lindenhof versicherung",
            interval=ContractInterval.YEARLY,
            expected_amount_cents=-6_480,
            next_due_date=add_months_clamped(today, 5),
            start_date=add_months_clamped(today, -19),
            min_term_end=add_months_clamped(today, 5),
            notice_period_days=90,
            confirmed_at=utcnow(),
            is_manual=True,
        )
    )


def _add_plans(
    db: Session,
    household_id: uuid.UUID,
    owner_id: uuid.UUID,
    savings: Account,
    categories: dict[str, Category],
    today: date,
) -> None:
    for name, cents in (("Lebensmittel", 45_000), ("Freizeit", 16_000), ("Mobilität", 18_000)):
        db.add(
            Budget(
                id=uuid.uuid4(),
                household_id=household_id,
                category_id=categories[name].id,
                amount_cents=cents,
            )
        )

    def goal(name: str, target: int, icon: str, color: str, **extra: object) -> SavingsGoal:
        return SavingsGoal(
            id=uuid.uuid4(),
            household_id=household_id,
            owner_user_id=owner_id,
            visibility=AccountVisibility.SHARED,
            name=name,
            target_cents=target,
            icon=icon,
            color=color,
            **extra,
        )

    vacation = goal("Sommerurlaub", 180_000, "plane", "chart-6", target_date=add_months_clamped(today, 7))
    reserve = goal("Notgroschen", 600_000, "shield", "chart-1", account_id=savings.id)
    db.add_all([vacation, reserve])
    db.flush()
    for months_ago, cents in ((3, 25_000), (2, 25_000), (1, 25_000), (0, 20_000)):
        db.add(
            SavingsContribution(
                id=uuid.uuid4(),
                goal_id=vacation.id,
                amount_cents=cents,
                booked_on=add_months_clamped(today, -months_ago).replace(day=1),
                created_by_id=owner_id,
            )
        )


def seed_demo(db: Session, password: str, *, today: date | None = None, seed: int = 7) -> DemoResult:
    """Create the demo household with two members, accounts, four months of bookings and plans."""
    if db.scalar(select(func.count()).select_from(User)):
        raise DemoRefusedError("The database already has users; the demo only runs on an empty one.")
    today = today or today_berlin()

    household, owner = _create_people(db, password)
    seed_default_categories(db, household.id)
    db.flush()
    categories = {
        c.name: c for c in db.scalars(select(Category).where(Category.household_id == household.id))
    }
    giro, savings, card = _create_accounts(db, household.id, owner.id)
    _create_rules(db, household.id, owner.id, categories)

    ledger = _Ledger(db, household.id)
    _book_fixed(ledger, today, giro, savings, categories["Sparen"])
    _book_everyday(ledger, today, giro, card, seed)
    db.flush()

    apply_rules(db, household.id, ledger.created)
    confirmed = _review_contracts(db, detect_contracts(db, household.id, today=today), ledger, today)
    _add_insurance(db, household.id, giro, categories["Haftpflicht"], today)
    _add_plans(db, household.id, owner.id, savings, categories, today)

    db.add(AuditLog(action="demo_seeded_cli", user_id=owner.id, details={"email": DEMO_EMAIL}))
    db.flush()
    return DemoResult(household_id=household.id, transactions=len(ledger.created), contracts=confirmed + 1)

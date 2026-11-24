"""German default category tree, seeded once per household."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Category, CategoryKind


@dataclass(frozen=True)
class TopLevel:
    name: str
    icon: str  # lucide-react icon name
    children: tuple[str, ...] = ()
    kind: CategoryKind = CategoryKind.EXPENSE


# Colors are the chart tokens chart-1..chart-8, assigned in a cycle.
COLOR_TOKENS = tuple(f"chart-{i}" for i in range(1, 9))

DEFAULT_TREE: tuple[TopLevel, ...] = (
    TopLevel(
        "Einnahmen",
        "wallet",
        ("Gehalt", "Kindergeld", "Erstattungen", "Zinsen & Dividenden", "Sonstige Einnahmen"),
        CategoryKind.INCOME,
    ),
    TopLevel("Wohnen", "house", ("Miete", "Nebenkosten", "Strom & Gas", "Internet & Telefon", "Einrichtung")),
    TopLevel("Lebensmittel", "shopping-basket", ("Supermarkt", "Bäckerei", "Getränke")),
    TopLevel("Mobilität", "car", ("Tanken", "ÖPNV", "Auto", "Taxi & Sharing")),
    TopLevel(
        "Versicherungen",
        "shield-check",
        ("Haftpflicht", "Krankenversicherung", "Kfz-Versicherung", "Hausrat", "Sonstige Versicherungen"),
    ),
    TopLevel("Freizeit", "ticket", ("Restaurant & Café", "Kultur & Events", "Sport", "Hobbys", "Reisen")),
    TopLevel("Shopping", "shopping-bag", ("Kleidung", "Elektronik", "Haushalt", "Geschenke")),
    TopLevel("Gesundheit", "heart-pulse", ("Apotheke", "Arzt", "Drogerie")),
    TopLevel("Abos & Medien", "tv", ("Streaming", "Software", "Zeitungen & Zeitschriften")),
    TopLevel("Kinder", "baby", ("Kita & Schule", "Kleidung & Spielzeug")),
    TopLevel("Steuern & Gebühren", "landmark", ("Bankgebühren", "Steuern", "Rundfunkbeitrag")),
    TopLevel("Spenden", "hand-heart"),
    TopLevel("Bargeld", "banknote", ("Abhebung",)),
    TopLevel("Sonstiges", "circle-ellipsis"),
    TopLevel("Umbuchung", "arrow-left-right", ("Eigene Konten", "Sparen"), CategoryKind.TRANSFER),
)


def seed_default_categories(db: Session, household_id: uuid.UUID) -> int:
    """Insert the default tree for a household and return the number of categories created."""
    created = 0
    for index, top in enumerate(DEFAULT_TREE):
        color = COLOR_TOKENS[index % len(COLOR_TOKENS)]
        parent = Category(
            id=uuid.uuid4(),
            household_id=household_id,
            name=top.name,
            kind=top.kind,
            icon=top.icon,
            color=color,
        )
        db.add(parent)
        created += 1
        for child_name in top.children:
            db.add(
                Category(
                    id=uuid.uuid4(),
                    household_id=household_id,
                    parent=parent,
                    name=child_name,
                    kind=top.kind,
                    color=color,
                )
            )
            created += 1
    db.flush()
    return created

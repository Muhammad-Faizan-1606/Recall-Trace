"""PostgreSQL competing transactions for the catalog slice, not stock posting."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import Item


def test_competing_duplicate_creation(records):
    company_id = records["companies"]["aurora"]
    engine = db.engine
    barrier = Barrier(2)

    def insert():
        with Session(engine) as session:
            session.add(
                Item(
                    organization_id=company_id, code="RACE", name="Competing item", kind="component"
                )
            )
            barrier.wait(timeout=10)
            try:
                session.commit()
                return "created"
            except IntegrityError:
                session.rollback()
                return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: insert(), range(2)))
    assert sorted(results) == ["created", "duplicate"]
    assert (
        len(
            db.session.scalars(
                select(Item).where(Item.organization_id == company_id, Item.code == "RACE")
            ).all()
        )
        == 1
    )


def test_separate_transactions_cannot_overwrite_stale_version(records):
    with Session(db.engine) as first, Session(db.engine) as second:
        a = first.get(Item, records["aurora_items"])
        b = second.get(Item, records["aurora_items"])
        a.name = "First committed edit"
        first.commit()
        b.name = "Stale edit"
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    db.session.expire_all()
    assert db.session.get(Item, records["aurora_items"]).name == "First committed edit"

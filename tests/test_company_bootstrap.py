"""A real installation must not depend on fictional demo accounts or data."""

from conftest import PASSWORD
from sqlalchemy import select

from app.extensions import db
from app.models import Item, Membership, Organization, Role, User


def test_empty_company_owner_and_core_permissions_bootstrap(app):
    runner = app.test_cli_runner()
    args = ["create-company", "--name", "Fictional bootstrap test", "--slug", "bootstrap-test"]
    assert runner.invoke(args=args).exit_code == 0
    result = runner.invoke(args=args)
    assert result.exit_code == 0 and "preserved unchanged" in result.output
    company = db.session.scalar(select(Organization).where(Organization.slug == "bootstrap-test"))
    assert db.session.scalar(select(Item.id).where(Item.organization_id == company.id)) is None
    assert (
        runner.invoke(
            args=[
                "create-owner",
                "--company",
                company.slug,
                "--email",
                "bootstrap@example.test",
                "--password",
                PASSWORD,
            ]
        ).exit_code
        == 0
    )
    assert runner.invoke(args=["init-business", "--company", company.slug]).exit_code == 0
    assert db.session.scalar(
        select(Role.id).where(Role.organization_id == company.id, Role.code == "owner")
    )
    user = db.session.scalar(select(User).where(User.email == "bootstrap@example.test"))
    assert db.session.scalar(
        select(Membership.id).where(
            Membership.organization_id == company.id, Membership.user_id == user.id
        )
    )
    assert (
        runner.invoke(
            args=["create-company", "--name", "Overwrite attempt", "--slug", company.slug]
        ).exit_code
        != 0
    )
    assert (
        runner.invoke(args=["create-company", "--name", "Invalid", "--slug", "../bad"]).exit_code
        != 0
    )
    db.session.refresh(company)
    assert company.name == "Fictional bootstrap test"

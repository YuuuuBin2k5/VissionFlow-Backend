"""Create or verify a local user and grant the initial administrator membership."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.bootstrap_organization import (  # noqa: E402
    BootstrapAdministrator,
    BootstrapAdministratorCommand,
)
from app.application.local_auth import (  # noqa: E402
    RegisterLocalUser,
    RegisterLocalUserCommand,
)
from app.core.config import Settings  # noqa: E402
from app.core.passwords import Argon2idPasswordHasher  # noqa: E402
from app.domain.authorization import OrganizationRole  # noqa: E402
from app.domain.local_auth import canonical_email  # noqa: E402
from app.infrastructure.bootstrap_repository import (  # noqa: E402
    SqlAlchemyBootstrapAdministratorRepository,
)
from app.infrastructure.local_auth_repository import SqlAlchemyLocalAuthRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a local VisionFlow login and grant administrator access."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--organization-slug", default="visionflow")
    parser.add_argument("--organization-name", default="VisionFlow")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required because this operation grants administrator access")

    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    settings = Settings.from_env(require_migration_url=True)
    engine = create_engine(settings.migration_database_url, pool_pre_ping=True)
    hasher = Argon2idPasswordHasher()
    email = canonical_email(args.email)

    with Session(engine) as session:
        auth_repository = SqlAlchemyLocalAuthRepository(session)
        user = auth_repository.find_by_email(email)
        user_created = user is None
        if user is None:
            user = RegisterLocalUser(auth_repository, hasher).execute(
                RegisterLocalUserCommand(
                    email=email,
                    password=password,
                    display_name=args.display_name,
                )
            )
        elif not hasher.verify(user.password_hash, password):
            raise SystemExit(
                "The account already exists but the supplied password does not match; "
                "no access changes were made"
            )

        result = BootstrapAdministrator(
            SqlAlchemyBootstrapAdministratorRepository(session)
        ).execute(
            BootstrapAdministratorCommand(
                organization_slug=args.organization_slug,
                organization_name=args.organization_name,
                identity_subject=f"local|{user.user_id}",
                email=email,
                display_name=args.display_name,
                role=OrganizationRole.ADMINISTRATOR,
                promote_existing_membership=False,
            )
        )

    print(
        "Local administrator bootstrap complete: "
        f"email={email} user_created={user_created} "
        f"organization_id={result.organization_id} user_id={result.user_id} "
        f"membership_created={result.membership_created}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

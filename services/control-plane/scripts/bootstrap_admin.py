from __future__ import annotations

import argparse
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
from app.core.config import Settings  # noqa: E402
from app.domain.authorization import OrganizationRole  # noqa: E402
from app.infrastructure.bootstrap_repository import SqlAlchemyBootstrapAdministratorRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a VisionFlow organization membership using MIGRATION_DATABASE_URL."
    )
    parser.add_argument("--organization-slug", required=True)
    parser.add_argument("--organization-name", required=True)
    parser.add_argument(
        "--identity-subject",
        required=True,
        help="Exact authenticated subject, e.g. local|<uuid> or service|visionflow-intelligence-worker",
    )
    parser.add_argument("--email")
    parser.add_argument("--display-name")
    parser.add_argument("--role", choices=[role.value for role in OrganizationRole], default="administrator")
    parser.add_argument("--promote-existing", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="Required acknowledgement for this write operation")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required because this operation writes administrator access")

    settings = Settings.from_env(require_migration_url=True)
    engine = create_engine(settings.migration_database_url, pool_pre_ping=True)
    with Session(engine) as session:
        result = BootstrapAdministrator(SqlAlchemyBootstrapAdministratorRepository(session)).execute(
            BootstrapAdministratorCommand(
                organization_slug=args.organization_slug,
                organization_name=args.organization_name,
                identity_subject=args.identity_subject,
                email=args.email,
                display_name=args.display_name,
                role=OrganizationRole(args.role),
                promote_existing_membership=args.promote_existing,
            )
        )
    print(
        "VisionFlow administrator bootstrap complete: "
        f"organization_id={result.organization_id} user_id={result.user_id} "
        f"membership_created={result.membership_created} membership_promoted={result.membership_promoted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

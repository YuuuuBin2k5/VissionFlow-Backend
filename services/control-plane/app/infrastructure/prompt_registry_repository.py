from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.prompt_registry import (
    AddPromptVersionCommand,
    CreatePromptTemplateCommand,
    PromotePromptVersionCommand,
    PromptKeyConflict,
    PromptTemplateSummary,
    PromptVersionSummary,
)
from app.infrastructure.models import PromptAuditEvent, PromptTemplate, PromptVersion


class SqlAlchemyPromptRegistryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_template(self, command: CreatePromptTemplateCommand) -> PromptTemplateSummary:
        template = PromptTemplate(
            organization_id=command.organization_id,
            prompt_key=command.prompt_key,
            name=command.name.strip(),
            description=command.description.strip(),
            production_version=1 if command.promote_immediately else None,
        )
        try:
            self._session.add(template)
            self._session.flush()
            self._session.add(
                PromptVersion(
                    prompt_template_id=template.id,
                    version=1,
                    content=command.content,
                    config=command.config,
                    change_note=command.change_note,
                )
            )
            self._audit(template, command.actor_subject, "prompt_template.created", {"version": 1})
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise PromptKeyConflict("prompt_key already exists in this organization") from exc
        except Exception:
            self._session.rollback()
            raise
        return _template_summary(template)

    def add_version(self, command: AddPromptVersionCommand) -> PromptVersionSummary:
        try:
            template = self._owned_template(command.organization_id, command.prompt_template_id, lock=True)
            version = (self._session.scalar(
                select(func.max(PromptVersion.version)).where(PromptVersion.prompt_template_id == template.id)
            ) or 0) + 1
            prompt_version = PromptVersion(
                prompt_template_id=template.id,
                version=version,
                content=command.content,
                config=command.config,
                change_note=command.change_note,
            )
            self._session.add(prompt_version)
            self._audit(template, command.actor_subject, "prompt_version.created", {"version": version})
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _version_summary(prompt_version)

    def promote_version(self, command: PromotePromptVersionCommand) -> PromptTemplateSummary:
        try:
            template = self._owned_template(command.organization_id, command.prompt_template_id, lock=True)
            prompt_version = self._session.scalar(
                select(PromptVersion).where(
                    PromptVersion.prompt_template_id == template.id,
                    PromptVersion.version == command.version,
                )
            )
            if prompt_version is None:
                raise LookupError(f"prompt version '{command.version}' was not found")
            template.production_version = prompt_version.version
            self._audit(template, command.actor_subject, "prompt_version.promoted", {"version": prompt_version.version})
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _template_summary(template)

    def list_templates(self, organization_id: uuid.UUID) -> list[PromptTemplateSummary]:
        templates = self._session.scalars(
            select(PromptTemplate)
            .where(PromptTemplate.organization_id == organization_id)
            .order_by(PromptTemplate.prompt_key)
        ).all()
        return [_template_summary(template) for template in templates]

    def list_versions(self, organization_id: uuid.UUID, prompt_template_id: uuid.UUID) -> list[PromptVersionSummary]:
        template = self._owned_template(organization_id, prompt_template_id, lock=False)
        versions = self._session.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_template_id == template.id)
            .order_by(PromptVersion.version.desc())
        ).all()
        return [_version_summary(version) for version in versions]

    def _owned_template(
        self, organization_id: uuid.UUID, prompt_template_id: uuid.UUID, *, lock: bool
    ) -> PromptTemplate:
        statement = select(PromptTemplate).where(
            PromptTemplate.id == prompt_template_id,
            PromptTemplate.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        template = self._session.scalar(statement)
        if template is None:
            raise LookupError(f"prompt template '{prompt_template_id}' was not found")
        return template

    def _audit(self, template: PromptTemplate, actor_subject: str, action: str, payload: dict[str, object]) -> None:
        self._session.add(
            PromptAuditEvent(
                organization_id=template.organization_id,
                prompt_template_id=template.id,
                action=action,
                actor_subject=actor_subject,
                payload=payload,
            )
        )


def _template_summary(template: PromptTemplate) -> PromptTemplateSummary:
    return PromptTemplateSummary(
        id=uuid.UUID(str(template.id)),
        prompt_key=template.prompt_key,
        name=template.name,
        description=template.description,
        production_version=template.production_version,
    )


def _version_summary(version: PromptVersion) -> PromptVersionSummary:
    return PromptVersionSummary(
        id=uuid.UUID(str(version.id)),
        version=version.version,
        content=version.content,
        config=version.config,
        change_note=version.change_note,
    )

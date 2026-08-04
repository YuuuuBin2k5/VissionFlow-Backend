from __future__ import annotations

import uuid
from typing import Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.models import (
    CreativeCommandReceipt,
    CreativeMessage,
    CreativeProposal,
    CreativeSession,
    CreativeTurn,
)


class SqlAlchemyCreativeSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_session(self, organization_id: uuid.UUID, creation_spec: dict) -> CreativeSession:
        db_session = CreativeSession(
            organization_id=organization_id,
            creation_spec=creation_spec,
            revision=0,
        )
        self._session.add(db_session)
        self._session.flush()
        return db_session

    def get_session(self, session_id: uuid.UUID, lock: bool = False) -> CreativeSession | None:
        query = select(CreativeSession).where(CreativeSession.id == session_id)
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def get_session_with_messages_and_proposals(
        self,
        session_id: uuid.UUID,
        message_limit: int,
        message_offset: int,
        proposal_limit: int,
        proposal_offset: int,
    ) -> Tuple[CreativeSession | None, list[CreativeMessage], int, list[CreativeProposal], int]:
        db_session = self.get_session(session_id)
        if not db_session:
            return None, [], 0, [], 0

        # Get Messages
        msg_query = (
            select(CreativeMessage)
            .where(CreativeMessage.session_id == session_id)
            .order_by(CreativeMessage.created_at.asc())
        )
        msg_count = self._session.scalar(
            select(func.count()).select_from(CreativeMessage).where(CreativeMessage.session_id == session_id)
        ) or 0
        messages = list(self._session.scalars(msg_query.limit(message_limit).offset(message_offset)).all())

        # Get Proposals
        prop_query = (
            select(CreativeProposal)
            .where(CreativeProposal.session_id == session_id)
            .order_by(CreativeProposal.version.asc())
        )
        prop_count = self._session.scalar(
            select(func.count()).select_from(CreativeProposal).where(CreativeProposal.session_id == session_id)
        ) or 0
        proposals = list(self._session.scalars(prop_query.limit(proposal_limit).offset(proposal_offset)).all())

        return db_session, messages, msg_count, proposals, prop_count

    def get_proposal(self, proposal_id: uuid.UUID) -> CreativeProposal | None:
        return self._session.scalar(select(CreativeProposal).where(CreativeProposal.id == proposal_id))

    def save_message(self, session_id: uuid.UUID, actor: str, content: str) -> CreativeMessage:
        msg = CreativeMessage(
            session_id=session_id,
            actor=actor,
            content=content,
        )
        self._session.add(msg)
        self._session.flush()
        return msg

    def save_proposal(
        self,
        session_id: uuid.UUID,
        message_id: uuid.UUID,
        parent_proposal_id: uuid.UUID | None,
        state: str,
        title: str,
        brief: str,
        script: str,
        scenes: list[dict],
        version: int,
        trace_id: str,
        generation_manifest: dict,
    ) -> CreativeProposal:
        proposal = CreativeProposal(
            session_id=session_id,
            message_id=message_id,
            parent_proposal_id=parent_proposal_id,
            state=state,
            title=title,
            brief=brief,
            script=script,
            scenes=scenes,
            version=version,
            trace_id=trace_id,
            generation_manifest=generation_manifest,
        )
        self._session.add(proposal)
        self._session.flush()
        return proposal

    def get_turn_by_idempotency_key(self, session_id: uuid.UUID, idempotency_key: str, lock: bool = False) -> CreativeTurn | None:
        query = select(CreativeTurn).where(
            CreativeTurn.session_id == session_id,
            CreativeTurn.idempotency_key == idempotency_key,
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def get_active_generating_turn(self, session_id: uuid.UUID, lock: bool = False) -> CreativeTurn | None:
        query = select(CreativeTurn).where(
            CreativeTurn.session_id == session_id,
            CreativeTurn.status == "generating",
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def save_turn(self, turn: CreativeTurn) -> None:
        self._session.add(turn)
        self._session.flush()

    def get_command_receipt(
        self, organization_id: uuid.UUID, operation_type: str, idempotency_key: str, lock: bool = False
    ) -> CreativeCommandReceipt | None:
        query = select(CreativeCommandReceipt).where(
            CreativeCommandReceipt.organization_id == organization_id,
            CreativeCommandReceipt.operation_type == operation_type,
            CreativeCommandReceipt.idempotency_key == idempotency_key,
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def save_command_receipt(self, receipt: CreativeCommandReceipt) -> None:
        self._session.add(receipt)
        self._session.flush()

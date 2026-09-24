import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from app.application.manage_creative_session import CreationSpecSchema
from app.domain.publish_metadata import (
    legacy_seo_to_publish_metadata,
    normalize_hashtags,
    normalize_tags,
    resolve_publish_metadata,
)
from app.routers.integrations import _issue_youtube_manifest


class PublishMetadataLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture_liminal = {
            "youtube": {
                "title": "Vì Sao Một Hành Lang Trống Lại Đáng Sợ?",
                "description": "Hiện tượng không gian chuyển tiếp (liminal space) khiến não bộ mất phương hướng vì thiếu điểm neo thực tế.\n\nCùng khám phá cơ chế tâm lý đằng sau cảm giác rợn ngợp này.",
                "hashtags": ["#KhongGianChuyenTiep", "#LiminalSpace", "#TamLyHoc", "#BiAn"],
                "tags": ["liminal space", "tâm lý học", "không gian chuyển tiếp"],
                "pinned_comment": "Bạn từng có cảm giác lạc vào một nơi quen mà lạ chưa?",
            }
        }

        self.fixture_dark_matter = {
            "youtube": {
                "title": "Một Cú Va Chạm Có Thể Là Vật Chất Tối?",
                "description": "Một science-mystery Short kể về sự kiện nuclear recoil bất thường mà LUX-ZEPLIN vừa công bố.\n\nLiệu đây có phải là dấu vết đầu tiên của vật chất tối hay chỉ là biến động thống kê 2.6 sigma?",
                "hashtags": ["#VatChatToi", "#DarkMatter", "#KhoaHoc", "#VuTru"],
                "tags": ["vật chất tối", "dark matter", "LUX ZEPLIN"],
                "pinned_comment": "2.6 sigma theo bạn đã đủ để hy vọng chưa?",
            }
        }

    # Test A: CreationSpecSchema ingests and preserves publish_metadata
    def test_a_creation_spec_schema_ingests_and_preserves_publish_metadata(self):
        payload = {
            "title": "Test Title",
            "brief": "Test Brief",
            "publish_metadata": self.fixture_dark_matter,
        }
        spec = CreationSpecSchema(**payload)
        dumped = spec.model_dump()
        self.assertIn("publish_metadata", dumped)
        self.assertEqual(dumped["publish_metadata"], self.fixture_dark_matter)
        self.assertEqual(
            dumped["publish_metadata"]["youtube"]["title"],
            "Một Cú Va Chạm Có Thể Là Vật Chất Tối?",
        )

    # Test B: Legacy SEO conversion
    def test_b_legacy_seo_to_publish_metadata(self):
        legacy_seo = {
            "title": "Legacy SEO Title",
            "description": "Legacy SEO Description line 1\nLine 2",
            "hashtags": ["#Tag1", "tag2", "#TAG1"],
            "tags": ["tag a", "tag b", "tag a"],
            "pinned_comment": "Pinned comment here",
        }
        converted = legacy_seo_to_publish_metadata(legacy_seo)
        self.assertIn("youtube", converted)
        yt = converted["youtube"]
        self.assertEqual(yt["title"], "Legacy SEO Title")
        self.assertEqual(yt["description"], "Legacy SEO Description line 1\nLine 2")
        self.assertEqual(yt["hashtags"], ["#Tag1", "#tag2"])  # deduplicated case-folded
        self.assertEqual(yt["tags"], ["tag a", "tag b"])
        self.assertEqual(yt["pinned_comment"], "Pinned comment here")

    # Test C: Authority Hierarchy - User final edit > Content AI > Fallback
    def test_c_authority_hierarchy(self):
        content_ai = {
            "youtube": {
                "title": "AI Title",
                "description": "AI Description",
                "hashtags": ["#AITag"],
                "tags": ["ai tag"],
            }
        }
        user_override = {
            "youtube": {
                "title": "User Title",
                "description": "User Description",
                "hashtags": ["#UserTag"],
            }
        }
        fallback = {
            "youtube": {
                "title": "Fallback Title",
                "description": "Fallback Description",
                "hashtags": ["#FallbackTag"],
            }
        }

        # Case 1: User override wins for title, description, hashtags; tags fall back to content AI
        resolved = resolve_publish_metadata(
            content_metadata=content_ai,
            user_metadata=user_override,
            fallback=fallback,
        )
        self.assertEqual(resolved.title.value, "User Title")
        self.assertEqual(resolved.title.source, "user")
        self.assertEqual(resolved.description.value, "User Description")
        self.assertEqual(resolved.description.source, "user")
        self.assertEqual(resolved.hashtags.value, ["#UserTag"])
        self.assertEqual(resolved.hashtags.source, "user")
        self.assertEqual(resolved.tags.value, ["ai tag"])
        self.assertEqual(resolved.tags.source, "content_ai")

        # Case 2: Content AI wins when user metadata is None
        resolved_ai = resolve_publish_metadata(
            content_metadata=content_ai,
            user_metadata=None,
            fallback=fallback,
        )
        self.assertEqual(resolved_ai.title.value, "AI Title")
        self.assertEqual(resolved_ai.title.source, "content_ai")
        self.assertEqual(resolved_ai.description.value, "AI Description")
        self.assertEqual(resolved_ai.description.source, "content_ai")
        self.assertEqual(resolved_ai.hashtags.value, ["#AITag"])
        self.assertEqual(resolved_ai.hashtags.source, "content_ai")

        # Case 3: Fallback wins when both user and content AI are None
        resolved_fb = resolve_publish_metadata(
            content_metadata=None,
            user_metadata=None,
            fallback=fallback,
        )
        self.assertEqual(resolved_fb.title.value, "Fallback Title")
        self.assertEqual(resolved_fb.title.source, "generated_fallback")
        self.assertEqual(resolved_fb.description.value, "Fallback Description")
        self.assertEqual(resolved_fb.description.source, "generated_fallback")

    def _setup_mock_manifest_session(self, project_title: str, project_brief: str):
        org_id = uuid.uuid4()
        conn_id = uuid.uuid4()

        approval = MagicMock()
        approval.export_asset_id = uuid.uuid4()

        artifact = MagicMock()
        artifact.object_key = "artifacts/video.mp4"
        artifact.byte_size = 10485760
        artifact.checksum_sha256 = "a" * 64

        connection = MagicMock()
        connection.id = conn_id
        connection.encrypted_refresh_token = "token123"

        project = MagicMock()
        project.title = project_title
        project.brief = project_brief

        session = MagicMock()
        # Side effect for scalar queries:
        # 1. PublishApproval
        # 2. MediaAsset (artifact)
        # 3. PublisherConnection
        # 4. WorkflowStep (intel)
        # 5. WorkflowStep (publish)
        session.scalar.side_effect = [
            approval,
            artifact,
            connection,
            None,
            None,
        ]
        session.get.return_value = project

        return session, org_id, conn_id

    # Test D: Manifest issuance with Canonical Fixture 19 (Liminal Space)
    def test_d_fixture_19_liminal_space_manifest(self):
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.project_id = uuid.uuid4()
        workflow.input_payload = {"publish_metadata": self.fixture_liminal}
        workflow.prompt_manifest = {"publish_metadata": self.fixture_liminal}

        session, org_id, conn_id = self._setup_mock_manifest_session(
            project_title="Vì Sao Một Hành Lang Trống Lại Đáng Sợ?",
            project_brief="Khám phá liminal space",
        )

        with patch("app.routers.integrations.PrivateObjectPreviewIssuer") as mock_preview_issuer, \
             patch("app.routers.integrations.YouTubeAccessTokenRefresher") as mock_refresher, \
             patch("app.routers.integrations.PublisherTokenCipher"), \
             patch("app.routers.integrations.YouTubePublisherSettings"):

            mock_preview = MagicMock()
            mock_preview.download_url = "https://storage.visionflow.io/video.mp4"
            mock_preview.expires_in_seconds = 3600
            mock_preview_issuer.from_env.return_value.issue_final_export.return_value = mock_preview

            mock_token = MagicMock()
            mock_token.value = "access_token_xyz"
            mock_token.expires_in_seconds = 3600
            mock_refresher.return_value.refresh.return_value = mock_token

            manifest = _issue_youtube_manifest(session, workflow, org_id, conn_id)

            # Assert Title
            self.assertEqual(manifest.title, "Vì Sao Một Hành Lang Trống Lại Đáng Sợ?")

            # Assert Description:
            # MUST contain original canonical text with newlines
            self.assertIn(
                "Hiện tượng không gian chuyển tiếp (liminal space) khiến não bộ mất phương hướng vì thiếu điểm neo thực tế.\n\nCùng khám phá cơ chế tâm lý đằng sau cảm giác rợn ngợp này.",
                manifest.description,
            )
            # MUST NOT prepend title to description
            self.assertFalse(manifest.description.startswith("Vì Sao Một Hành Lang Trống Lại Đáng Sợ?...\n"))

            # MUST include explicit hashtags
            for h in ["#KhongGianChuyenTiep", "#LiminalSpace", "#TamLyHoc", "#BiAn"]:
                self.assertIn(h, manifest.description)
                self.assertIn(h, manifest.hashtags)

            # MUST NOT contain generic fallback tags
            self.assertNotIn("#KhamPha", manifest.description)
            self.assertNotIn("#KienThucThuVi", manifest.description)
            self.assertNotIn("#ChuyenLa", manifest.description)
            self.assertNotIn("#GocChiemNghiem", manifest.description)

            # Tags & Pinned comment
            self.assertEqual(manifest.tags, ["liminal space", "tâm lý học", "không gian chuyển tiếp"])
            self.assertEqual(manifest.pinned_comment, "Bạn từng có cảm giác lạc vào một nơi quen mà lạ chưa?")

    # Test E: Manifest issuance with Canonical Fixture 20 (Dark Matter)
    def test_e_fixture_20_dark_matter_manifest(self):
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.project_id = uuid.uuid4()
        workflow.input_payload = {"publish_metadata": self.fixture_dark_matter}
        workflow.prompt_manifest = {"publish_metadata": self.fixture_dark_matter}

        session, org_id, conn_id = self._setup_mock_manifest_session(
            project_title="Một Cú Va Chạm Có Thể Là Vật Chất Tối?",
            project_brief="Science mystery LUX-ZEPLIN",
        )

        with patch("app.routers.integrations.PrivateObjectPreviewIssuer") as mock_preview_issuer, \
             patch("app.routers.integrations.YouTubeAccessTokenRefresher") as mock_refresher, \
             patch("app.routers.integrations.PublisherTokenCipher"), \
             patch("app.routers.integrations.YouTubePublisherSettings"):

            mock_preview = MagicMock()
            mock_preview.download_url = "https://storage.visionflow.io/dark_matter.mp4"
            mock_preview.expires_in_seconds = 3600
            mock_preview_issuer.from_env.return_value.issue_final_export.return_value = mock_preview

            mock_token = MagicMock()
            mock_token.value = "access_token_xyz"
            mock_token.expires_in_seconds = 3600
            mock_refresher.return_value.refresh.return_value = mock_token

            manifest = _issue_youtube_manifest(session, workflow, org_id, conn_id)

            self.assertEqual(manifest.title, "Một Cú Va Chạm Có Thể Là Vật Chất Tối?")
            self.assertIn("Một science-mystery Short kể về sự kiện nuclear recoil bất thường mà LUX-ZEPLIN vừa công bố.", manifest.description)
            for h in ["#VatChatToi", "#DarkMatter", "#KhoaHoc", "#VuTru"]:
                self.assertIn(h, manifest.description)
                self.assertIn(h, manifest.hashtags)

            self.assertNotIn("#KhamPha", manifest.description)
            self.assertNotIn("#KienThucThuVi", manifest.description)
            self.assertNotIn("#ChuyenLa", manifest.description)
            self.assertNotIn("#GocChiemNghiem", manifest.description)

            self.assertEqual(manifest.tags, ["vật chất tối", "dark matter", "LUX ZEPLIN"])
            self.assertEqual(manifest.pinned_comment, "2.6 sigma theo bạn đã đủ để hy vọng chưa?")

    # Test F: Fallback to build_high_converting_description ONLY when description is truly absent
    def test_f_fallback_to_high_converting_when_no_metadata(self):
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.project_id = uuid.uuid4()
        workflow.input_payload = {}
        workflow.prompt_manifest = {}

        session, org_id, conn_id = self._setup_mock_manifest_session(
            project_title="Bí Ẩn Tam Giác Bermuda",
            project_brief="Hồ sơ tàu ma mất tích bí ẩn",
        )

        with patch("app.routers.integrations.PrivateObjectPreviewIssuer") as mock_preview_issuer, \
             patch("app.routers.integrations.YouTubeAccessTokenRefresher") as mock_refresher, \
             patch("app.routers.integrations.PublisherTokenCipher"), \
             patch("app.routers.integrations.YouTubePublisherSettings"):

            mock_preview = MagicMock()
            mock_preview.download_url = "https://storage.visionflow.io/bermuda.mp4"
            mock_preview.expires_in_seconds = 3600
            mock_preview_issuer.from_env.return_value.issue_final_export.return_value = mock_preview

            mock_token = MagicMock()
            mock_token.value = "access_token_xyz"
            mock_token.expires_in_seconds = 3600
            mock_refresher.return_value.refresh.return_value = mock_token

            manifest = _issue_youtube_manifest(session, workflow, org_id, conn_id)

            # Fallback should kick in and produce description
            self.assertTrue(len(manifest.description) > 0)
            self.assertEqual(manifest.title, "Bí Ẩn Tam Giác Bermuda")

    # Test G: publisher-worker does not re-generate description or overwrite manifest
    def test_g_publisher_worker_preserves_manifest_description(self):
        pw_dir = BACKEND_ROOT / "services" / "publisher-worker"
        publisher_main = pw_dir / "main.py"
        if str(pw_dir) not in sys.path:
            sys.path.insert(0, str(pw_dir))
        import importlib.util
        spec = importlib.util.spec_from_file_location("publisher_worker_main", str(publisher_main))
        pw_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pw_module)

        manifest = {
            "title": "Một Cú Va Chạm Có Thể Là Vật Chất Tối?",
            "description": "Một mô tả đầy đủ, riêng cho video...",
            "hashtags": ["#VatChatToi", "#DarkMatter"],
            "tags": ["vật chất tối"],
            "access_token": "valid_token",
            "artifact_download_url": "https://fake/video.mp4",
            "artifact_byte_size": 100,
            "artifact_checksum_sha256": "0" * 64,
        }

        session = MagicMock()
        with patch.object(pw_module, "_download_verified_artifact"), \
             patch.object(pw_module, "YouTubeResumableUploader") as mock_uploader_cls:

            mock_uploader = MagicMock()
            mock_uploader_cls.return_value = mock_uploader
            upload_result = MagicMock()
            upload_result.video_id = "vid_123"
            upload_result.url = "https://youtu.be/vid_123"
            mock_uploader.upload.return_value = upload_result

            video_id, url = pw_module._upload_manifest(session, manifest)

            self.assertEqual(video_id, "vid_123")
            uploaded_metadata = mock_uploader.upload.call_args.kwargs["metadata"]
            self.assertEqual(uploaded_metadata.description, "Một mô tả đầy đủ, riêng cho video...")
            self.assertNotIn("#KhamPha", uploaded_metadata.description)

    # Test H: ManageCreativeSession create_manual_proposal persists publish_metadata in manifest
    def test_h_manage_creative_session_create_manual_proposal_persists_publish_metadata(self):
        from app.application.manage_creative_session import ManageCreativeSession

        saved_proposals = []
        mock_repo = MagicMock()
        mock_sess = MagicMock()
        mock_sess.organization_id = uuid.uuid4()
        mock_sess.workflow_run_id = None
        mock_sess.revision = 1
        mock_repo.get_session.return_value = mock_sess
        mock_repo.get_command_receipt.return_value = None

        def fake_save_proposal(**kwargs):
            prop = MagicMock()
            prop.id = uuid.uuid4()
            prop.generation_manifest = kwargs.get("generation_manifest")
            saved_proposals.append(prop)
            return prop

        mock_repo.save_proposal.side_effect = fake_save_proposal

        db_session = MagicMock()
        db_session.scalar.return_value = 0
        session_maker = MagicMock()
        session_maker.return_value.__enter__.return_value = db_session

        with patch("app.application.manage_creative_session.SqlAlchemyCreativeSessionRepository", return_value=mock_repo):
            manager = ManageCreativeSession(
                session_maker=session_maker,
                provider_adapter=MagicMock(),
            )
            prop_id = manager.create_manual_proposal(
                session_id=uuid.uuid4(),
                organization_id=mock_sess.organization_id,
                expected_session_revision=1,
                idempotency_key="a" * 32,
                title="Test Proposal Title",
                brief="Test Brief that is long enough",
                script="This is a test script that easily exceeds the minimum length of forty characters.",
                scenes=[
                    {"scene_id": "1", "narration": "Narration 1", "duration_seconds": 5},
                    {"scene_id": "2", "narration": "Narration 2", "duration_seconds": 5},
                    {"scene_id": "3", "narration": "Narration 3", "duration_seconds": 5},
                ],
                publish_metadata=self.fixture_dark_matter,
            )

        self.assertEqual(len(saved_proposals), 1)
        manifest = saved_proposals[0].generation_manifest
        self.assertIn("publish_metadata", manifest)
        self.assertEqual(manifest["publish_metadata"], self.fixture_dark_matter)

    # Test I: ManageCreativeSession create_proposal_revision inherits publish_metadata from parent
    def test_i_manage_creative_session_create_proposal_revision_inherits_parent_metadata(self):
        from app.application.manage_creative_session import ManageCreativeSession

        saved_revisions = []
        mock_repo = MagicMock()
        mock_sess = MagicMock()
        mock_sess.organization_id = uuid.uuid4()
        mock_sess.workflow_run_id = None
        mock_sess.revision = 2
        mock_repo.get_session.return_value = mock_sess
        mock_repo.get_command_receipt.return_value = None

        parent_prop = MagicMock()
        parent_prop.id = uuid.uuid4()
        parent_prop.session_id = uuid.uuid4()
        parent_prop.trace_id = "trace-123"
        parent_prop.message_id = uuid.uuid4()
        parent_prop.generation_manifest = {"publish_metadata": self.fixture_liminal}
        mock_repo.get_proposal.return_value = parent_prop

        def fake_save_proposal(**kwargs):
            prop = MagicMock()
            prop.id = uuid.uuid4()
            prop.generation_manifest = kwargs.get("generation_manifest")
            saved_revisions.append(prop)
            return prop

        mock_repo.save_proposal.side_effect = fake_save_proposal

        db_session = MagicMock()
        db_session.scalar.return_value = 1
        session_maker = MagicMock()
        session_maker.return_value.__enter__.return_value = db_session

        with patch("app.application.manage_creative_session.SqlAlchemyCreativeSessionRepository", return_value=mock_repo):
            manager = ManageCreativeSession(
                session_maker=session_maker,
                provider_adapter=MagicMock(),
            )
            # Without passing explicit publish_metadata, it should inherit from parent
            manager.create_proposal_revision(
                session_id=parent_prop.session_id,
                parent_proposal_id=parent_prop.id,
                organization_id=mock_sess.organization_id,
                expected_session_revision=2,
                idempotency_key="b" * 32,
                title="Revised Title",
                brief="Revised Brief",
                script="This is a revised script that is long enough to satisfy forty character minimum.",
                scenes=[
                    {"scene_id": "1", "narration": "Narration 1", "duration_seconds": 5},
                    {"scene_id": "2", "narration": "Narration 2", "duration_seconds": 5},
                    {"scene_id": "3", "narration": "Narration 3", "duration_seconds": 5},
                ],
                publish_metadata=None,
            )

        self.assertEqual(len(saved_revisions), 1)
        manifest = saved_revisions[0].generation_manifest
        self.assertIn("publish_metadata", manifest)
        self.assertEqual(manifest["publish_metadata"], self.fixture_liminal)

    # Test J: create_workflow_draft_from_session propagates publish_metadata to input_payload and prompt_manifest
    def test_j_create_workflow_draft_propagates_publish_metadata(self):
        from app.application.manage_creative_session import ManageCreativeSession

        mock_repo = MagicMock()
        mock_sess = MagicMock()
        mock_sess.id = uuid.uuid4()
        mock_sess.organization_id = uuid.uuid4()
        mock_sess.workflow_run_id = None
        mock_sess.creation_spec = {
            "title": "Session Title",
            "brief": "Session Brief",
            "format_profile": "short_vertical",
            "timezone": "Asia/Bangkok",
            "publish_metadata": self.fixture_dark_matter,
        }
        mock_repo.get_session.return_value = mock_sess

        accepted_prop = MagicMock()
        accepted_prop.id = uuid.uuid4()
        accepted_prop.session_id = mock_sess.id
        accepted_prop.state = "accepted"
        accepted_prop.title = "Accepted Title"
        accepted_prop.brief = "Accepted Brief"
        accepted_prop.script = "Accepted Script with sufficient character count"
        accepted_prop.scenes = [
            {"scene_id": "1", "narration": "Narration 1", "duration_seconds": 15},
            {"scene_id": "2", "narration": "Narration 2", "duration_seconds": 15},
            {"scene_id": "3", "narration": "Narration 3", "duration_seconds": 15},
        ]
        accepted_prop.trace_id = "trace-456"
        accepted_prop.generation_manifest = {
            "source": "manual",
            "publish_metadata": self.fixture_dark_matter,
        }
        mock_repo.get_proposal.return_value = accepted_prop

        captured_commands = []
        mock_wf_repo = MagicMock()
        def fake_initial_run(command):
            captured_commands.append(command)
            wf = MagicMock()
            wf.id = uuid.uuid4()
            return wf, False
        mock_wf_repo._create_or_get_initial_run_in_transaction.side_effect = fake_initial_run

        mock_doc_repo = MagicMock()
        mock_doc = MagicMock()
        mock_doc_ver = MagicMock()
        mock_doc_ver.id = uuid.uuid4()
        mock_doc_repo._save_in_transaction.return_value = (mock_doc, mock_doc_ver)

        db_session = MagicMock()
        db_session.scalar.return_value = None  # No prior receipt
        session_maker = MagicMock()
        session_maker.return_value.__enter__.return_value = db_session

        with patch("app.application.manage_creative_session.SqlAlchemyCreativeSessionRepository", return_value=mock_repo), \
             patch("app.application.manage_creative_session.SqlAlchemyShortFormWorkflowRepository", return_value=mock_wf_repo), \
             patch("app.application.manage_creative_session.SqlAlchemyCreativeDocumentRepository", return_value=mock_doc_repo):

            manager = ManageCreativeSession(
                session_maker=session_maker,
                provider_adapter=MagicMock(),
            )
            res = manager.create_workflow_draft_from_session(
                session_id=mock_sess.id,
                organization_id=mock_sess.organization_id,
                accepted_proposal_id=accepted_prop.id,
                client_idempotency_key="client-draft-12345678",
            )

        self.assertEqual(len(captured_commands), 1)
        cmd = captured_commands[0]
        # Verify input_payload
        self.assertIn("publish_metadata", cmd.input_payload)
        self.assertEqual(cmd.input_payload["publish_metadata"], self.fixture_dark_matter)
        # Verify prompt_manifest
        self.assertIn("publish_metadata", cmd.prompt_manifest)
        self.assertEqual(cmd.prompt_manifest["publish_metadata"], self.fixture_dark_matter)

    # Test K: worker domain parity test for legacy_seo_to_publish_metadata
    def test_k_worker_domain_legacy_seo_parity(self):
        from worker.domain.publish_metadata import legacy_seo_to_publish_metadata as worker_legacy_seo

        legacy = {
            "title": "Worker Title",
            "caption_seo": "Worker Description\nLine 2",
            "hashtags": ["#WorkerTag1", "#WorkerTag2"],
            "tags": ["tag1", "tag2"],
        }
        res = worker_legacy_seo(legacy)
        self.assertIn("youtube", res)
        self.assertEqual(res["youtube"]["title"], "Worker Title")
        self.assertEqual(res["youtube"]["description"], "Worker Description\nLine 2")
        self.assertEqual(res["youtube"]["hashtags"], ["#WorkerTag1", "#WorkerTag2"])
        self.assertEqual(res["youtube"]["tags"], ["tag1", "tag2"])

    # Test L: No duplicate hashtags when description already has them
    def test_l_no_duplicate_hashtags_when_already_in_description(self):
        desc_with_tags = (
            "Mô tả video về vật chất tối.\n\n"
            "#VatChatToi #DarkMatter #KhoaHoc #VuTru"
        )
        meta = {
            "youtube": {
                "title": "Vật chất tối",
                "description": desc_with_tags,
                "hashtags": ["#VatChatToi", "#DarkMatter", "#KhoaHoc", "#VuTru"],
            }
        }
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.project_id = uuid.uuid4()
        workflow.input_payload = {"publish_metadata": meta}
        workflow.prompt_manifest = {"publish_metadata": meta}

        session, org_id, conn_id = self._setup_mock_manifest_session(
            project_title="Vật chất tối",
            project_brief="Brief",
        )

        with patch("app.routers.integrations.PrivateObjectPreviewIssuer") as mock_preview_issuer, \
             patch("app.routers.integrations.YouTubeAccessTokenRefresher") as mock_refresher, \
             patch("app.routers.integrations.PublisherTokenCipher"), \
             patch("app.routers.integrations.YouTubePublisherSettings"):

            mock_preview = MagicMock()
            mock_preview.download_url = "https://storage.visionflow.io/v.mp4"
            mock_preview.expires_in_seconds = 3600
            mock_preview_issuer.from_env.return_value.issue_final_export.return_value = mock_preview

            mock_token = MagicMock()
            mock_token.value = "token"
            mock_token.expires_in_seconds = 3600
            mock_refresher.return_value.refresh.return_value = mock_token

            manifest = _issue_youtube_manifest(session, workflow, org_id, conn_id)

            # Check that #VatChatToi appears exactly once in the description
            self.assertEqual(manifest.description.count("#VatChatToi"), 1)
            self.assertEqual(manifest.description.count("#DarkMatter"), 1)


if __name__ == "__main__":
    unittest.main()



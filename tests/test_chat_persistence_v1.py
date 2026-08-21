"""Targeted Acceptance & Regression Test Suite for App V1 SQLite Chat Persistence.

Verifies:
- Chat session creation and message persistence in SQLite (data/app_v1.sqlite)
- App restart recovery (new manager instance loads existing DB data)
- Sidebar hydration ordering (updated_at DESC)
- Session rename, archive, and delete (cascade)
- Attachment persistence in SQLite
- Multi-chat isolation
- Knowledge safety invariants (CROSS_CHAT_KNOWLEDGE_LEAK_COUNT = 0, no auto-promotion to Global/Brand)
- Failed execution retains user message
- Brain RC3 frozen hashes and 5 permanent agents preservation
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from chat.knowledge import SessionKnowledgeStore
from chat.repository import SQLiteChatRepository
from chat.session import AttachmentType, ChatAttachment, ChatRole, ChatSessionManager
from governance.access_matrix import AgentAccessMatrix, PERMANENT_FIVE_AGENTS
from knowledge.repository import LocalKnowledgeRepository


class TestChatPersistenceV1(unittest.TestCase):
    """Test suite for local SQLite chat persistence and restart survival."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_app_v1.sqlite")
        self.repo = SQLiteChatRepository(db_path=self.db_path)
        self.chat_mgr = ChatSessionManager(repository=self.repo)
        self.session_knowledge = SessionKnowledgeStore()
        self.knowledge_repo = LocalKnowledgeRepository()

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Creation & Message Persistence
    def test_chat_creation_persists_to_sqlite(self):
        """Verify chat session is written immediately to SQLite."""
        session = self.chat_mgr.create_session(title="Q4 Campaign Strategy")
        self.assertIsNotNone(session.chat_id)
        self.assertEqual(session.title, "Q4 Campaign Strategy")

        # Directly query repository
        stored = self.repo.get_session(session.chat_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.chat_id, session.chat_id)
        self.assertEqual(stored.title, "Q4 Campaign Strategy")

    def test_message_persistence_to_sqlite(self):
        """Verify user and assistant messages persist to SQLite."""
        session = self.chat_mgr.create_session(title="Test Messages")
        u_msg = self.chat_mgr.add_user_message(session.chat_id, "User input text")
        a_msg = self.chat_mgr.add_assistant_response(session.chat_id, "Assistant response text")

        stored = self.chat_mgr.get_session(session.chat_id)
        self.assertEqual(len(stored.messages), 2)
        self.assertEqual(stored.messages[0].content, "User input text")
        self.assertEqual(stored.messages[0].role, ChatRole.USER)
        self.assertEqual(stored.messages[1].content, "Assistant response text")
        self.assertEqual(stored.messages[1].role, ChatRole.ASSISTANT)

    # 2. Restart Acceptance Test
    def test_restart_recovery_across_instances(self):
        """Verify closing connection and creating fresh manager reloads all data intact."""
        # 1. Create sessions and messages in instance A
        s1 = self.chat_mgr.create_session(title="Chat Session 1")
        self.chat_mgr.add_user_message(s1.chat_id, "Message 1 in Session 1")
        self.chat_mgr.add_assistant_response(s1.chat_id, "Response 1 in Session 1")

        s2 = self.chat_mgr.create_session(title="Chat Session 2")
        self.chat_mgr.add_user_message(s2.chat_id, "Message 1 in Session 2")

        self.repo.close()

        # 2. Simulate App Restart: Create new repo & manager pointing to same DB file
        new_repo = SQLiteChatRepository(db_path=self.db_path)
        new_chat_mgr = ChatSessionManager(repository=new_repo)

        sessions = new_chat_mgr.list_sessions()
        self.assertEqual(len(sessions), 2)

        loaded_s1 = new_chat_mgr.get_session(s1.chat_id)
        self.assertIsNotNone(loaded_s1)
        self.assertEqual(loaded_s1.title, "Chat Session 1")
        self.assertEqual(len(loaded_s1.messages), 2)
        self.assertEqual(loaded_s1.messages[0].content, "Message 1 in Session 1")
        self.assertEqual(loaded_s1.messages[1].content, "Response 1 in Session 1")

        loaded_s2 = new_chat_mgr.get_session(s2.chat_id)
        self.assertIsNotNone(loaded_s2)
        self.assertEqual(loaded_s2.title, "Chat Session 2")
        self.assertEqual(len(loaded_s2.messages), 1)
        self.assertEqual(loaded_s2.messages[0].content, "Message 1 in Session 2")

        new_repo.close()

    # 3. Sidebar Hydration & Ordering
    def test_sidebar_hydration_ordering(self):
        """Verify list_sessions returns sessions ordered by updated_at DESC."""
        s1 = self.chat_mgr.create_session(title="First Chat")
        s2 = self.chat_mgr.create_session(title="Second Chat")

        # Update s1 with a message
        self.chat_mgr.add_user_message(s1.chat_id, "Recent activity in first chat")

        sessions = self.chat_mgr.list_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].chat_id, s1.chat_id)
        self.assertEqual(sessions[1].chat_id, s2.chat_id)

    # 4. Rename, Archive, and Delete
    def test_rename_chat_persists(self):
        """Verify renaming a chat updates SQLite and survives reload."""
        session = self.chat_mgr.create_session(title="Old Name")
        updated = self.chat_mgr.update_session(session.chat_id, title="New Renamed Title")
        self.assertEqual(updated.title, "New Renamed Title")

        # Reload from fresh manager
        new_repo = SQLiteChatRepository(db_path=self.db_path)
        new_chat_mgr = ChatSessionManager(repository=new_repo)
        reloaded = new_chat_mgr.get_session(session.chat_id)
        self.assertEqual(reloaded.title, "New Renamed Title")
        new_repo.close()

    def test_archive_chat_filters_from_default_list(self):
        """Verify archiving a chat hides it from default list but keeps data."""
        session = self.chat_mgr.create_session(title="To Archive")
        self.chat_mgr.update_session(session.chat_id, archived=True)

        active_list = self.chat_mgr.list_sessions(include_archived=False)
        self.assertEqual(len(active_list), 0)

        all_list = self.chat_mgr.list_sessions(include_archived=True)
        self.assertEqual(len(all_list), 1)
        self.assertTrue(all_list[0].archived)

    def test_delete_chat_cascades_messages_and_attachments(self):
        """Verify deleting a chat cascades deletion in SQLite."""
        session = self.chat_mgr.create_session(title="To Delete")
        att = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url="doc.pdf",
            attachment_type=AttachmentType.PDF,
            content="PDF binary/text content",
        )
        self.chat_mgr.add_user_message(session.chat_id, "Message to be deleted", attachments=[att])

        # Verify exists
        self.assertIsNotNone(self.chat_mgr.get_session(session.chat_id))

        # Delete
        ok = self.chat_mgr.delete_session(session.chat_id)
        self.assertTrue(ok)

        # Verify not found
        self.assertIsNone(self.chat_mgr.get_session(session.chat_id))

        # Verify cascade in SQLite tables
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (session.chat_id,))
            msg_count = cursor.fetchone()[0]
            self.assertEqual(msg_count, 0)

            cursor.execute("SELECT COUNT(*) FROM chat_attachments WHERE chat_id = ?", (session.chat_id,))
            att_count = cursor.fetchone()[0]
            self.assertEqual(att_count, 0)

    # 5. Multi-Chat Isolation & Ephemeral Attachment Isolation
    def test_multi_chat_isolation_and_attachments(self):
        """Verify attachments and messages in Chat A are not visible in Chat B."""
        chat_a = self.chat_mgr.create_session(title="Chat A")
        chat_b = self.chat_mgr.create_session(title="Chat B")

        att_a = ChatAttachment(
            chat_id=chat_a.chat_id,
            filename_or_url="brand_secret_a.txt",
            attachment_type=AttachmentType.TEXT,
            content="Secret content exclusive to Chat A",
        )
        self.chat_mgr.add_user_message(chat_a.chat_id, "User query A", attachments=[att_a])
        self.session_knowledge.index_attachment(att_a)

        self.chat_mgr.add_user_message(chat_b.chat_id, "User query B")

        # Check DB isolation
        session_a = self.chat_mgr.get_session(chat_a.chat_id)
        session_b = self.chat_mgr.get_session(chat_b.chat_id)
        self.assertEqual(len(session_a.messages[0].attachments), 1)
        self.assertEqual(len(session_b.messages[0].attachments), 0)

        # Check ephemeral session knowledge search isolation
        res_a = self.session_knowledge.search_session(chat_a.chat_id, query="Secret")
        res_b = self.session_knowledge.search_session(chat_b.chat_id, query="Secret")
        self.assertEqual(len(res_a), 1)
        self.assertEqual(len(res_b), 0)

    # 6. Zero Knowledge Auto-Promotion
    def test_zero_knowledge_auto_promotion(self):
        """Verify chat session attachments NEVER automatically write to LocalKnowledgeRepository."""
        chat = self.chat_mgr.create_session(title="Strict Knowledge Isolation")
        initial_count = len(self.knowledge_repo.list_documents())

        att = ChatAttachment(
            chat_id=chat.chat_id,
            filename_or_url="private_notes.md",
            attachment_type=AttachmentType.MARKDOWN,
            content="# Private Notes\nDo not promote to persistent knowledge.",
        )
        self.chat_mgr.add_user_message(chat.chat_id, "Save this note", attachments=[att])
        self.session_knowledge.index_attachment(att)

        final_count = len(self.knowledge_repo.list_documents())
        self.assertEqual(initial_count, final_count)

    # 7. Error Retention: Failed Run Retains User Message
    def test_failed_run_retains_user_message(self):
        """Verify that when an error occurs, the user message is safely in SQLite."""
        session = self.chat_mgr.create_session(title="Failure Test")
        u_msg = self.chat_mgr.add_user_message(session.chat_id, "Critical prompt that failed execution")

        # Record error status assistant message
        err_msg = self.chat_mgr.add_assistant_response(
            session.chat_id,
            content="⚠️ [Runtime Execution Error]: Provider timed out.\nYour message was preserved in local history.",
            status="ERROR",
        )

        loaded = self.chat_mgr.get_session(session.chat_id)
        self.assertEqual(len(loaded.messages), 2)
        self.assertEqual(loaded.messages[0].message_id, u_msg.message_id)
        self.assertEqual(loaded.messages[0].content, "Critical prompt that failed execution")
        self.assertEqual(loaded.messages[1].status, "ERROR")

    # 8. Brain Invariants Preservation
    def test_five_agent_brain_invariants(self):
        """Verify permanent agent count = 5 and frozen Brain RC3 hashes are intact."""
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(len(PERMANENT_FIVE_AGENTS), 5)

        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(perf_md.encode("utf-8")).hexdigest(),
            "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9",
        )

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(cmo_md.encode("utf-8")).hexdigest(),
            "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e",
        )

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(handoff_py.encode("utf-8")).hexdigest(),
            "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a",
        )


if __name__ == "__main__":
    unittest.main()

import json
import os
import shutil
import tempfile
import unittest

from src.analysis.role_analyzer import GroupMessageAnalyzer, RoleAnalyzer
from src.isolation.file_store import IsolatedFileStore, PathSanitizer
from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
from src.knowledge.collector import KnowledgeCollector
from src.knowledge.fts_repo import FtsKnowledgeRepository
from src.memory.conversation import ConversationMemory, ConversationStore
from src.models.contracts import TaskDraft, TaskStatus
from src.pool.agent_pool import AgentPool
from src.rooms.space_registry import SpaceRegistry
from src.store.database import Database
from src.store.task_repo import TaskRepository


class TestTaskRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def _make_draft(self, title: str = "test task", **kw) -> TaskDraft:
        return TaskDraft(
            title=title,
            description=kw.get("description", ""),
            project_id=kw.get("project_id", "p1"),
            source_message_ids=kw.get("source_message_ids", ["m1"]),
            assignee_user_id=kw.get("assignee_user_id", "u1"),
            confidence=kw.get("confidence", 0.9),
        )

    def test_save_and_list_drafts(self):
        d1 = self._make_draft("任务A", project_id="p1")
        d2 = self._make_draft("任务B", project_id="p2")
        id1 = self.repo.save_draft(d1)
        id2 = self.repo.save_draft(d2)
        self.assertGreater(id1, 0)
        self.assertGreater(id2, 0)

        all_p1 = self.repo.list_drafts(project_id="p1")
        self.assertEqual(len(all_p1), 1)
        self.assertEqual(all_p1[0]["title"], "任务A")

        all_pending = self.repo.list_drafts()
        self.assertGreaterEqual(len(all_pending), 2)

    def test_confirm_draft_creates_task(self):
        did = self.repo.save_draft(self._make_draft())
        task = self.repo.confirm_draft(did)
        self.assertIsNotNone(task)
        self.assertEqual(task.title, "test task")
        self.assertEqual(task.id, f"task-{did}")

        tasks = self.repo.list_tasks(project_id="p1")
        self.assertEqual(len(tasks), 1)

        drafts = self.repo.list_drafts(status="pending")
        self.assertEqual(len(drafts), 0)

    def test_confirm_missing_draft(self):
        task = self.repo.confirm_draft(9999)
        self.assertIsNone(task)

    def test_dismiss_draft(self):
        did = self.repo.save_draft(self._make_draft())
        self.repo.dismiss_draft(did)
        drafts = self.repo.list_drafts(status="pending")
        self.assertEqual(len(drafts), 0)

    def test_update_task_status(self):
        did = self.repo.save_draft(self._make_draft())
        task = self.repo.confirm_draft(did)
        self.repo.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        tasks = self.repo.list_tasks(project_id="p1")
        self.assertEqual(tasks[0].status, TaskStatus.IN_PROGRESS)

    def test_list_tasks_empty_project(self):
        self.assertEqual(self.repo.list_tasks(project_id="nonexistent"), [])

    def test_create_task_direct(self):
        task = self.repo.create_task("direct task", "desc", "p1", assignee_user_id="u-alice")
        self.assertTrue(task.id.startswith("task-"))
        self.assertEqual(task.title, "direct task")
        self.assertEqual(task.project_id, "p1")
        self.assertEqual(task.assignee_user_id, "u-alice")
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        tasks = self.repo.list_tasks(project_id="p1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, task.id)

    def test_create_task_minimal(self):
        task = self.repo.create_task("minimal", "", "p2")
        self.assertEqual(task.title, "minimal")
        self.assertIsNone(task.assignee_user_id)
        tasks = self.repo.list_tasks(project_id="p2")
        self.assertEqual(len(tasks), 1)


class TestMessagePersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_save_and_list_messages(self):
        id1 = self.repo.save_message("space-1", "alice", "dev login")
        id2 = self.repo.save_message("space-1", "bob", "ok i do it")
        id3 = self.repo.save_message("space-2", "charlie", "deploy ci")
        self.assertGreater(id1, 0)

        all_msgs = self.repo.list_messages()
        self.assertEqual(len(all_msgs), 3)

        space1_msgs = self.repo.list_messages(space_id="space-1")
        self.assertEqual(len(space1_msgs), 2)
        self.assertEqual(space1_msgs[0]["id"], id2)
        self.assertEqual(space1_msgs[1]["id"], id1)

    def test_mark_processed(self):
        self.repo.save_message("s1", "a", "msg1")
        self.repo.save_message("s1", "b", "msg2")
        unprocessed = self.repo.load_unprocessed_messages()
        self.assertEqual(len(unprocessed), 2)

        self.repo.mark_messages_processed("s1")
        unprocessed = self.repo.load_unprocessed_messages()
        self.assertEqual(len(unprocessed), 0)

    def test_message_limit(self):
        for i in range(5):
            self.repo.save_message("s1", "u", f"msg{i}")
        msgs = self.repo.list_messages(space_id="s1", limit=3)
        self.assertEqual(len(msgs), 3)

    def test_message_keyword_search(self):
        self.repo.save_message("s1", "alice", "开发登录功能")
        self.repo.save_message("s1", "bob", "修复登录bug")
        self.repo.save_message("s1", "charlie", "部署CI/CD")
        msgs = self.repo.list_messages(keyword="登录")
        self.assertEqual(len(msgs), 2)

    def test_message_since_filter(self):
        import time
        self.repo.save_message("s1", "a", "old msg")
        time.sleep(1.1)
        import datetime
        since = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        self.repo.save_message("s1", "b", "new msg")
        msgs_after = self.repo.list_messages(since=since)
        self.assertEqual(len(msgs_after), 1)
        self.assertEqual(msgs_after[0]["content"], "new msg")


class TestReminders(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_save_and_list_reminders(self):
        r1 = self.repo.save_reminder("task-1", "space-a", "已逾期", "请关注 task-1")
        r2 = self.repo.save_reminder("task-2", "space-b", "阻塞", "task-2 需处理")
        self.assertGreater(r1, 0)

        all_rem = self.repo.list_reminders()
        self.assertEqual(len(all_rem), 2)

        space_a = self.repo.list_reminders(space_id="space-a")
        self.assertEqual(len(space_a), 1)
        self.assertEqual(space_a[0]["task_id"], "task-1")

    def test_dismiss_reminder(self):
        rid = self.repo.save_reminder("t1", "s1", "逾期", "催办 t1")
        self.repo.dismiss_reminder(rid)
        active = self.repo.list_reminders(space_id="s1")
        self.assertEqual(len(active), 0)
        all_r = self.repo.list_reminders(space_id="s1", include_dismissed=True)
        self.assertGreaterEqual(len(all_r), 1)


class TestTaskDependencies(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def _make_task(self, task_id: str, title: str) -> None:
        self.repo._conn.execute(
            "INSERT INTO tasks (id, title, description, project_id, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, title, "", "test-proj", TaskStatus.CONFIRMED.value),
        )
        self.repo._conn.commit()

    def test_set_dependency(self):
        self._make_task("task-a", "Task A")
        self._make_task("task-b", "Task B")
        self.repo.set_dependency("task-b", "task-a")
        blocked_by = self.repo.get_blocked_by("task-b")
        self.assertEqual(blocked_by, "task-a")

    def test_get_blockers_of(self):
        self._make_task("task-a", "Task A")
        self._make_task("task-b", "Task B")
        self._make_task("task-c", "Task C")
        self.repo.set_dependency("task-b", "task-a")
        self.repo.set_dependency("task-c", "task-a")
        blockers = self.repo.get_blockers_of("task-a")
        self.assertEqual(sorted(blockers), sorted(["task-b", "task-c"]))

    def test_cascade_unblock(self):
        self._make_task("task-a", "Task A")
        self._make_task("task-b", "Task B")
        self.repo.set_dependency("task-b", "task-a")
        self.repo.update_task_status("task-b", TaskStatus.BLOCKED)
        unblocked = self.repo.cascade_unblock("task-a")
        self.assertIn("task-b", unblocked)
        blocked_by = self.repo.get_blocked_by("task-b")
        self.assertIsNone(blocked_by)

    def test_done_cascades_unblock(self):
        self._make_task("task-a", "Task A")
        self._make_task("task-b", "Task B")
        self.repo.set_dependency("task-b", "task-a")
        self.repo.update_task_status("task-b", TaskStatus.BLOCKED)
        self.repo.update_task_status("task-a", TaskStatus.DONE)
        blocked_by = self.repo.get_blocked_by("task-b")
        self.assertIsNone(blocked_by)


class TestRoleAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_role_cache_load(self):
        fpath = os.path.join(self.tmpdir, "agent_alice.json")
        data = {"role": "前端工程师", "department": "工程部", "responsibilities": ["前端开发"]}
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        role = analyzer.get_role("alice")
        self.assertIsNotNone(role)
        self.assertEqual(role["role"], "前端工程师")
        self.assertEqual(role["department"], "工程部")
        self.assertEqual(role["responsibilities"], ["前端开发"])

        role2 = analyzer.get_role("nobody")
        self.assertIsNone(role2)

    def test_role_cache_skips_non_json(self):
        with open(os.path.join(self.tmpdir, "readme.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(self.tmpdir, "agent_alice.json"), "w", encoding="utf-8") as f:
            json.dump({"role": "后端工程师"}, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        role = analyzer.get_role("alice")
        self.assertIsNotNone(role)
        self.assertEqual(role["role"], "后端工程师")

    def test_reload_cache(self):
        fpath = os.path.join(self.tmpdir, "agent_bob.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({"role": "测试工程师"}, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        self.assertIsNotNone(analyzer.get_role("bob"))

        # Write new file after initial scan
        fpath2 = os.path.join(self.tmpdir, "agent_charlie.json")
        with open(fpath2, "w", encoding="utf-8") as f:
            json.dump({"role": "安全工程师"}, f, ensure_ascii=False)

        self.assertIsNone(analyzer.get_role("charlie"))
        analyzer.reload()
        self.assertIsNotNone(analyzer.get_role("charlie"))

    def test_guess_role_keywords(self):
        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)

        result = analyzer.guess_role("unknown", "今天完成了上线部署和监控配置")
        self.assertEqual(result["role"], "运维工程师")

        result = analyzer.guess_role("u2", "产品需求文档需要更新")
        self.assertEqual(result["role"], "产品经理")

        result = analyzer.guess_role("u3", "修复登录页面的 bug")
        self.assertEqual(result["role"], "测试工程师")

        result = analyzer.guess_role("u4", "这个页面的样式需要调整")
        self.assertEqual(result["role"], "前端工程师")

        result = analyzer.guess_role("u5", "nothing interesting here just chat")
        self.assertEqual(result["role"], "未知")

    def test_guess_role_empty_content(self):
        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        result = analyzer.guess_role("u1", "")
        self.assertEqual(result["role"], "未知")

    def test_guess_role_cache_priority(self):
        fpath = os.path.join(self.tmpdir, "agent_dave.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({"role": "架构师", "department": "技术部"}, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        result = analyzer.guess_role("dave", "修复一个前端的 bug")
        self.assertEqual(result["role"], "架构师")
        self.assertFalse(result.get("_guessed", False))

    def test_group_analyze(self):
        fpath = os.path.join(self.tmpdir, "agent_alice.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({"role": "前端工程师", "department": "工程部"}, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        ga = GroupMessageAnalyzer(analyzer)

        messages = [
            {"from_user_id": "alice", "content": "完成页面组件开发"},
            {"from_user_id": "bob", "content": "服务器部署上线了"},
            {"from_user_id": "alice", "content": "修复样式 bug"},
        ]

        results = ga.analyze(messages)
        self.assertEqual(len(results), 2)

        alice = next(r for r in results if r["user_id"] == "alice")
        self.assertEqual(alice["message_count"], 2)
        self.assertEqual(alice["role"], "前端工程师")
        self.assertEqual(alice["dept"], "工程部")

        bob = next(r for r in results if r["user_id"] == "bob")
        self.assertEqual(bob["message_count"], 1)
        self.assertEqual(bob["role"], "运维工程师")

    def test_group_summarize(self):
        fpath = os.path.join(self.tmpdir, "agent_alice.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({"role": "前端工程师"}, f, ensure_ascii=False)

        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        ga = GroupMessageAnalyzer(analyzer)

        messages = [
            {"from_user_id": "alice", "content": "页面组件需要重构"},
            {"from_user_id": "alice", "content": "前端渲染优化"},
            {"from_user_id": "bob", "content": "数据库查询优化"},
        ]

        summary = ga.summarize(messages)
        self.assertIn("前端工程师", summary)
        self.assertEqual(summary["前端工程师"]["count"], 2)
        self.assertEqual(summary["前端工程师"]["users"], ["alice"])
        self.assertGreater(len(summary["前端工程师"]["key_topics"]), 0)

        self.assertIn("后端工程师", summary)
        self.assertEqual(summary["后端工程师"]["count"], 1)
        self.assertEqual(summary["后端工程师"]["users"], ["bob"])

    def test_group_analyze_empty(self):
        analyzer = RoleAnalyzer(memory_dir=self.tmpdir)
        ga = GroupMessageAnalyzer(analyzer)

        self.assertEqual(ga.analyze([]), [])
        self.assertEqual(ga.summarize([]), {})


class TestPathSanitizer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normal_path(self):
        ps = PathSanitizer(self.tmpdir)
        result = ps.sanitize("file.txt")
        expected = os.path.realpath(os.path.join(self.tmpdir, "file.txt"))
        self.assertEqual(result, expected)

    def test_traversal_blocked(self):
        ps = PathSanitizer(self.tmpdir)
        with self.assertRaises(ValueError):
            ps.sanitize("../../../etc/passwd")

    def test_dotdot_blocked(self):
        ps = PathSanitizer(self.tmpdir)
        with self.assertRaises(ValueError):
            ps.sanitize("..secret")


class TestIsolatedFileStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.store = IsolatedFileStore(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_read(self):
        content = b"hello world"
        rel = self.store.write("u1", "space-a", "hello.txt", content)
        self.assertIn("hello.txt", rel)

        data = self.store.read("u1", "space-a", "hello.txt")
        self.assertEqual(data, content)

    def test_cross_user_isolation(self):
        self.store.write("alice", "proj", "secret.txt", b"alice data")

        with self.assertRaises(FileNotFoundError):
            self.store.read("bob", "proj", "secret.txt")

    def test_list_files(self):
        self.store.write("alice", "proj", "a.txt", b"a")
        self.store.write("bob", "proj", "b.txt", b"bb")

        files = self.store.list_files("proj")
        self.assertEqual(len(files), 2)
        user_ids = {f["user_id"] for f in files}
        self.assertEqual(user_ids, {"alice", "bob"})
        fnames = {f["filename"] for f in files}
        self.assertEqual(fnames, {"a.txt", "b.txt"})

    def test_list_user_files(self):
        self.store.write("alice", "proj", "x.txt", b"x")
        self.store.write("bob", "proj", "y.txt", b"yy")

        alice_files = self.store.list_user_files("alice", "proj")
        self.assertEqual(len(alice_files), 1)
        self.assertEqual(alice_files[0]["filename"], "x.txt")
        self.assertEqual(alice_files[0]["user_id"], "alice")

        bob_files = self.store.list_user_files("bob", "proj")
        self.assertEqual(len(bob_files), 1)
        self.assertEqual(bob_files[0]["filename"], "y.txt")

    def test_delete(self):
        self.store.write("u1", "proj", "del.txt", b"data")
        self.assertTrue(self.store.delete("u1", "proj", "del.txt"))
        self.assertFalse(self.store.delete("u1", "proj", "del.txt"))

        with self.assertRaises(FileNotFoundError):
            self.store.read("u1", "proj", "del.txt")


class TestAgentPool(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = AgentPool()

    def test_register(self):
        info = self.pool.register("alice", role="产品经理", department="产品部")
        self.assertEqual(info.user_id, "alice")
        self.assertEqual(info.role, "产品经理")
        self.assertEqual(info.department, "产品部")

    def test_record_activity(self):
        self.pool.register("bob")
        info = self.pool.record_activity("bob")
        self.assertIsNotNone(info)
        self.assertGreater(info.last_active, 0)
        self.assertEqual(info.message_count, 1)

    def test_stats(self):
        self.pool.register("alice")
        self.pool.record_activity("alice")
        self.pool.register("bob")
        stats = self.pool.stats()
        self.assertEqual(stats["total_agents"], 2)
        self.assertEqual(stats["active_agents"], 1)
        self.assertEqual(stats["idle_agents"], 1)
        self.assertEqual(stats["total_messages_processed"], 1)

    def test_list_agents_sorted(self):
        self.pool.register("alice")
        self.pool.record_activity("alice")
        self.pool.register("bob")
        agents = self.pool.list_agents()
        self.assertEqual(agents[0]["user_id"], "alice")
        self.assertEqual(agents[1]["user_id"], "bob")

    def test_remove(self):
        self.pool.register("alice")
        self.pool.remove("alice")
        self.assertIsNone(self.pool.get("alice"))
        self.assertEqual(self.pool.stats()["total_agents"], 0)

    def test_update_info(self):
        self.pool.register("alice")
        self.pool.update_info("alice", role="开发", department="技术部")
        info = self.pool.get("alice")
        self.assertEqual(info.role, "开发")
        self.assertEqual(info.department, "技术部")


class TestSpaceRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SpaceRegistry()

    def test_register(self):
        r = self.registry.register("proj-alpha", name="Alpha Project", space_type="project")
        self.assertEqual(r.space_id, "proj-alpha")
        self.assertEqual(r.name, "Alpha Project")
        self.assertEqual(r.space_type, "project")

    def test_list_all(self):
        self.registry.register("proj-a", name="A")
        self.registry.register("proj-b", name="B")
        spaces = self.registry.list_all()
        self.assertEqual(len(spaces), 2)

    def test_get(self):
        self.registry.register("proj-x", name="X")
        r = self.registry.get("proj-x")
        self.assertIsNotNone(r)
        self.assertEqual(r.name, "X")
        self.assertIsNone(self.registry.get("nonexistent"))

    def test_add_member(self):
        self.registry.register("proj-x")
        r = self.registry.add_member("proj-x", "alice")
        self.assertIn("alice", r.members)
        self.registry.add_member("proj-x", "alice")
        self.assertEqual(len(r.members), 1)

    def test_add_member_auto_creates_space(self):
        r = self.registry.add_member("new-space", "bob")
        self.assertEqual(r.space_id, "new-space")
        self.assertIn("bob", r.members)

    def test_delete(self):
        self.registry.register("proj-x")
        self.assertTrue(self.registry.delete("proj-x"))
        self.assertIsNone(self.registry.get("proj-x"))

    def test_stats(self):
        self.registry.register("a", name="A", space_type="department")
        self.registry.register("b", name="B")
        s = self.registry.stats()
        self.assertEqual(s["total_spaces"], 2)
        self.assertEqual(s["spaces"][0]["type"], "department")


class TestFtsKnowledgeRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = FtsKnowledgeRepository(self.db.connect())

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def _make_entry(self, eid: str, owner_type: KnowledgeOwnerType, owner_id: str, content: str) -> KnowledgeEntry:
        return KnowledgeEntry(id=eid, owner_type=owner_type, owner_id=owner_id, content=content)

    def test_save_and_list(self):
        e1 = self._make_entry("k1", KnowledgeOwnerType.PERSONAL, "alice", "Alice's notes about design")
        e2 = self._make_entry("k2", KnowledgeOwnerType.PROJECT, "proj-x", "Project specs")
        self.repo.save(e1)
        self.repo.save(e2)
        personal = self.repo.list_for_owner(KnowledgeOwnerType.PERSONAL, "alice")
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0].content, "Alice's notes about design")

    def test_search(self):
        self.repo.save(self._make_entry("k1", KnowledgeOwnerType.PERSONAL, "alice", "API design for login"))
        self.repo.save(self._make_entry("k2", KnowledgeOwnerType.PROJECT, "proj-x", "Design system guidelines"))
        self.repo.save(self._make_entry("k3", KnowledgeOwnerType.PERSONAL, "bob", "Deployment steps"))
        results = self.repo.search("design", user_id="alice")
        self.assertEqual(len(results), 2)

    def test_search_acl(self):
        self.repo.save(self._make_entry("k1", KnowledgeOwnerType.PERSONAL, "alice", "Alice secret"))
        self.repo.save(self._make_entry("k2", KnowledgeOwnerType.PROJECT, "proj-x", "Project notes"))
        results_alice = self.repo.search("secret", user_id="alice")
        self.assertEqual(len(results_alice), 1)
        results_bob = self.repo.search("secret", user_id="bob")
        self.assertEqual(len(results_bob), 0)

    def test_delete(self):
        self.repo.save(self._make_entry("k1", KnowledgeOwnerType.PERSONAL, "alice", "test"))
        self.assertTrue(self.repo.delete("k1"))
        self.assertFalse(self.repo.delete("k1"))

    def test_stats(self):
        self.repo.save(self._make_entry("k1", KnowledgeOwnerType.PERSONAL, "a", "a"))
        self.repo.save(self._make_entry("k2", KnowledgeOwnerType.PROJECT, "p", "p"))
        s = self.repo.stats()
        self.assertEqual(s["total_entries"], 2)


class TestKnowledgeCollector(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = FtsKnowledgeRepository(self.db.connect())
        self.collector = KnowledgeCollector(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_collect_text(self):
        entry = self.collector.collect_text("hello world", "Test Doc", owner_id="proj-a")
        self.assertIsNotNone(entry)
        self.assertIn("hello world", entry.content)
        results = self.repo.search("hello", user_id="", space_id="proj-a")
        self.assertGreaterEqual(len(results), 1)

    def test_collect_text_tags(self):
        entry = self.collector.collect_text("content", "Doc", tags=["api", "guide"])
        self.assertIn("api", entry.tags)
        self.assertIn("guide", entry.tags)

    def test_collect_bad_url(self):
        entry = self.collector.collect_url("http://127.0.0.1:99999/nonexistent")
        self.assertIsNone(entry)

    def test_collect_nonexistent_file(self):
        entry = self.collector.collect_file("/tmp/nonexistent_xyz_file.txt")
        self.assertIsNone(entry)

    def test_stats(self):
        self.collector.collect_text("a", "A")
        self.collector.collect_text("b", "B")
        s = self.collector.stats()
        self.assertEqual(s["repo"]["total_entries"], 2)


class TestConversationMemory(unittest.TestCase):
    def test_add_and_context(self):
        mem = ConversationMemory("agent-1")
        mem.add("user", "Hello")
        mem.add("assistant", "Hi there")
        ctx = mem.get_context()
        self.assertIn("Hello", ctx)
        self.assertIn("Hi there", ctx)

    def test_max_turns(self):
        mem = ConversationMemory("a", max_turns=3)
        for i in range(5):
            mem.add("user", str(i))
        self.assertEqual(len(mem.to_dict()), 3)
        self.assertEqual(mem.to_dict()[0]["content"], "2")

    def test_clear(self):
        mem = ConversationMemory("a")
        mem.add("user", "x")
        mem.clear()
        self.assertEqual(mem.get_context(), "")

    def test_store_get(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        store = ConversationStore(d)
        m1 = store.get("alice")
        m1.add("user", "msg1")
        store.save_all()
        m2 = store.get("alice")
        self.assertEqual(len(m2.to_dict()), 1)
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_record(self):
        store = ConversationStore("./data/test_conv")
        store.record("test-agent", "user", "hello")
        mem = store.get("test-agent")
        self.assertGreaterEqual(len(mem.to_dict()), 1)


class TestDeadlineTracker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_set_deadline(self):
        from src.orchestrator.deadline_tracker import DeadlineTracker
        self.repo._conn.execute(
            "INSERT INTO tasks (id,title,description,project_id,status) VALUES (?,?,?,?,?)",
            ("t1", "Test", "", "p1", TaskStatus.IN_PROGRESS.value),
        )
        self.repo._conn.commit()
        tracker = DeadlineTracker(self.repo)
        ok = tracker.set_deadline("t1", "2026-12-31 23:59:59")
        self.assertTrue(ok)

    def test_check_no_due(self):
        from src.orchestrator.deadline_tracker import DeadlineTracker
        self.repo._conn.execute(
            "INSERT INTO tasks (id,title,description,project_id,status) VALUES (?,?,?,?,?)",
            ("t2", "NoDue", "", "p1", TaskStatus.IN_PROGRESS.value),
        )
        self.repo._conn.commit()
        tracker = DeadlineTracker(self.repo)
        rems = tracker.check_and_remind("p1")
        self.assertEqual(len(rems), 0)


class TestTaskSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = Database(self.tmp)
        self.repo = TaskRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_search_by_keyword(self):
        self.repo.create_task("修复登录页面", "", "p1")
        self.repo.create_task("优化数据库查询", "", "p1")
        self.repo.create_task("写单元测试", "", "p2")
        r1 = self.repo.search_tasks("登录")
        self.assertEqual(len(r1), 1)
        self.assertEqual(r1[0].title, "修复登录页面")
        r2 = self.repo.search_tasks("数据")
        self.assertEqual(len(r2), 1)
        r3 = self.repo.search_tasks("xyz")
        self.assertEqual(len(r3), 0)

    def test_search_with_project_filter(self):
        self.repo.create_task("Task A", "", "proj-1")
        self.repo.create_task("Task A copy", "", "proj-2")
        r = self.repo.search_tasks("Task A", project_id="proj-1")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].project_id, "proj-1")


if __name__ == "__main__":
    unittest.main()

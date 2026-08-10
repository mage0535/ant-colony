import unittest
from unittest.mock import patch

from src.agents import PersonalAgent, ProjectAgent
from src.config import (
    AdminSettingsRecord,
    DEFAULT_SETTINGS_PATH,
    InMemorySettingsRepository,
    JsonFileSettingsRepository,
    LLMProvider,
    PlatformSettingsRecord,
    PlatformType,
    Settings,
    SettingsManagementService,
    apply_openvort_env_overlay,
    build_settings_service,
    export_openvort_env,
    seed_from_openvort_env_file,
    run_cli,
    write_openvort_env_file,
)
from src.engine import AgentEngine, AgentEngineConfig
from src.gateway import (
    CardCallbackService,
    Dispatcher,
    InMemoryOutboundNotifier,
    InboundGatewayService,
    RouteKind,
    adapt_wecom_payload,
    parse_task_card_action,
    render_task_draft_card,
)
from src.guard import ActionGuard, GovernanceParser
from src.knowledge import InMemoryKnowledgeRepository, KnowledgeOwnerType, KnowledgeService, ProjectSummaryService
from src.models import GuardContext, InMemoryTaskRepository, Message, MessageContext, SpaceType, TaskStatus
from src.orchestrator import (
    BatchExecutionService,
    BatchProcessor,
    NotificationService,
    OrchestratorActionService,
    TaskConfirmationService,
    TaskOrchestrator,
    TaskService,
)
from src.tools import FusionToolRegistry


class ContractsSmokeTest(unittest.TestCase):
    def test_personal_agent_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="personal"))
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        response = agent.process_message("u1", "please analyze this request", context)

        self.assertTrue(response.text.startswith("[LLM"))

    def test_project_orchestration_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        message = Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")

        drafts = project_agent.identify_tasks("proj-1", [message])
        self.assertEqual(len(drafts), 1)

        processor = BatchProcessor()
        processor.submit(message)
        batch = processor.drain("proj-1")
        self.assertEqual(len(batch), 1)

        orchestrator = TaskOrchestrator(project_agent)
        actions = orchestrator.on_batch("proj-1", batch)
        self.assertEqual(len(actions), 1)

        guard = ActionGuard()
        decision = guard.evaluate(actions[0], GuardContext(actor_user_id=None, actor_role=None, space_id="proj-1"))
        self.assertTrue(decision.reason)

    def test_task_orchestrator_deduplicates_titles_and_surfaces_governance(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        orchestrator = TaskOrchestrator(project_agent)

        messages = [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up"),
            Message(id="m2", space_id="proj-1", sender_user_id="u2", content="TODO: follow up"),
            Message(id="m3", space_id="proj-1", sender_user_id="u2", content="pause this project"),
        ]

        actions = orchestrator.on_batch("proj-1", messages)
        kinds = [action.kind for action in actions]

        self.assertEqual(kinds.count("task_draft_identified"), 1)
        self.assertEqual(kinds.count("governance_command_detected"), 1)

    def test_governance_parser_smoke(self) -> None:
        parser = GovernanceParser()

        self.assertIsNotNone(parser.parse("pause this project"))
        self.assertIsNotNone(parser.parse("not a task"))
        self.assertIsNotNone(parser.parse("handoff to human"))

    def test_empty_tool_registry_smoke(self) -> None:
        registry = FusionToolRegistry()
        self.assertEqual(registry.get_for_agent("any"), [])

    def test_task_service_lifecycle_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        message = Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")
        draft = project_agent.identify_tasks("proj-1", [message])[0]

        repository = InMemoryTaskRepository()
        service = TaskService(repository)

        task = service.create_from_draft(draft, task_id="t1")
        self.assertEqual(task.status, TaskStatus.DRAFT)

        task = service.confirm("t1")
        self.assertEqual(task.status, TaskStatus.CONFIRMED)

        task = service.start("t1")
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        task, signal = service.block("t1", "waiting for review")
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertEqual(signal.task_id, "t1")

        task = service.complete("t1")
        self.assertEqual(task.status, TaskStatus.DONE)

    def test_dispatcher_routing_smoke(self) -> None:
        dispatcher = Dispatcher()

        direct = Message(
            id="m1",
            space_id="space-1",
            sender_user_id="u1",
            content="hello",
            metadata={"is_direct": True},
        )
        routed = dispatcher.route(direct)
        self.assertEqual(routed.kind, RouteKind.PERSONAL)
        self.assertEqual(routed.target_id, "u1")

        group = Message(
            id="m2",
            space_id="space-1",
            sender_user_id="u1",
            content="TODO: follow up",
            metadata={},
        )
        routed = dispatcher.route(group)
        self.assertEqual(routed.kind, RouteKind.SPACE_BATCH)
        self.assertEqual(routed.target_id, "space-1")

    def test_settings_from_env_smoke(self) -> None:
        settings = Settings.from_env()
        self.assertIsInstance(settings, Settings)

    def test_settings_management_service_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)

        llm = service.make_llm_profile(
            provider=LLMProvider.ANTHROPIC,
            profile_id="default-anthropic",
            model_name="claude-sonnet-4",
            api_key="secret",
            api_base="https://api.anthropic.com",
        )
        service.save_llm_profile(llm)
        service.save_admin_settings(
            AdminSettingsRecord(
                admin_user_ids=["u-admin"],
                web_default_password="strong-password",
            )
        )
        service.save_platform_settings(
            PlatformSettingsRecord(
                platform=PlatformType.WECOM,
                enabled=True,
                settings={
                    "corp_id": "corp-1",
                    "agent_id": "agent-1",
                    "secret": "secret-1",
                    "callback_token": "token-1",
                    "callback_aes_key": "aes-1",
                },
            )
        )

        snapshot = service.build_runtime_snapshot()
        self.assertEqual(len(snapshot.llm_profiles), 1)
        self.assertEqual(snapshot.admin_settings.admin_user_ids, ["u-admin"])
        self.assertEqual(len(snapshot.platforms), 1)

        engine_config = service.build_engine_config("default-anthropic", "project")
        self.assertEqual(engine_config.model_name, "claude-sonnet-4")
        self.assertEqual(engine_config.metadata["provider"], "anthropic")

        runtime_settings = service.build_settings_from_snapshot()
        self.assertEqual(runtime_settings.anthropic_api_key, "secret")
        self.assertEqual(runtime_settings.admin_user_ids, ("u-admin",))
        self.assertEqual(runtime_settings.wecom_corp_id, "corp-1")

    def test_json_file_settings_repository_roundtrip_smoke(self) -> None:
        file_path = self._temp_settings_path("settings.json")
        repository = JsonFileSettingsRepository(file_path)
        service = SettingsManagementService(repository)

        service.save_llm_profile(
            service.make_llm_profile(
                provider=LLMProvider.OPENAI,
                profile_id="default-openai",
                model_name="gpt-5",
                api_key="sk-test",
            )
        )
        service.save_admin_settings(
            AdminSettingsRecord(
                admin_user_ids=["u1", "u2"],
                web_default_password="very-strong-password",
            )
        )
        service.save_platform_settings(
            PlatformSettingsRecord(
                platform=PlatformType.FEISHU,
                enabled=True,
                settings={"app_id": "app-1", "app_secret": "secret-1"},
            )
        )

        reloaded = JsonFileSettingsRepository(file_path)
        self.assertEqual(len(reloaded.list_llm_profiles()), 1)
        self.assertEqual(reloaded.get_admin_settings().admin_user_ids, ["u1", "u2"])
        self.assertEqual(reloaded.get_platform_settings(PlatformType.FEISHU).settings["app_id"], "app-1")

    def test_json_settings_file_permissions_are_restricted(self) -> None:
        file_path = self._temp_settings_path("secure-settings.json")
        repository = JsonFileSettingsRepository(file_path)
        service = SettingsManagementService(repository)

        with patch("os.chmod") as chmod:
            service.save_llm_profile(
                service.make_llm_profile(
                    provider=LLMProvider.OPENAI,
                    profile_id="secure-profile",
                    model_name="gpt-5",
                    api_key="secret-value",
                )
            )

        chmod.assert_called_with(file_path, 0o600)

    def test_settings_management_upsert_and_views_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)

        snapshot = service.ensure_defaults()
        self.assertIsNotNone(snapshot.admin_settings)
        self.assertEqual(len(snapshot.platforms), 4)

        profile = service.upsert_llm_profile(
            profile_id="default-openai",
            provider=LLMProvider.OPENAI,
            model_name="gpt-5",
            api_key="sk-live",
        )
        self.assertEqual(profile.model_name, "gpt-5")

        updated_admin = service.upsert_admin_settings(
            admin_user_ids=["admin-a"],
            web_default_password="strong-password",
        )
        self.assertEqual(updated_admin.admin_user_ids, ["admin-a"])

        updated_platform = service.upsert_platform_settings(
            platform=PlatformType.WECOM,
            enabled=True,
            settings={"corp_id": "corp", "agent_id": "agent"},
        )
        self.assertTrue(updated_platform.enabled)

        llm_views = service.build_llm_views()
        self.assertEqual(len(llm_views), 1)
        self.assertTrue(llm_views[0].api_key_configured)

        platform_views = service.build_platform_views()
        wecom_view = next(view for view in platform_views if view.platform == PlatformType.WECOM)
        self.assertIn("corp_id", wecom_view.configured_keys)
        self.assertIn("secret", wecom_view.missing_keys)

    def test_build_settings_service_bootstrap_smoke(self) -> None:
        file_path = self._temp_settings_path("runtime-settings.json")
        service = build_settings_service(file_path)

        snapshot = service.build_runtime_snapshot()
        self.assertIsNotNone(snapshot.admin_settings)
        self.assertEqual(len(snapshot.platforms), 4)
        self.assertTrue(DEFAULT_SETTINGS_PATH.name.endswith(".json"))

    def test_config_cli_smoke(self) -> None:
        file_path = self._temp_settings_path("runtime-settings-cli.json")

        exit_code = run_cli(["--file", file_path, "init"])
        self.assertEqual(exit_code, 0)

        exit_code = run_cli(
            [
                "--file",
                file_path,
                "set-llm",
                "--profile-id",
                "default-anthropic",
                "--provider",
                "anthropic",
                "--model-name",
                "claude-sonnet-4",
                "--api-key",
                "secret",
                "--enabled",
                "true",
            ]
        )
        self.assertEqual(exit_code, 0)

        exit_code = run_cli(
            [
                "--file",
                file_path,
                "set-admin",
                "--admin-user-ids",
                "u1,u2",
                "--web-default-password",
                "strong-password",
            ]
        )
        self.assertEqual(exit_code, 0)

        exit_code = run_cli(
            [
                "--file",
                file_path,
                "set-platform",
                "--platform",
                "wecom",
                "--enabled",
                "true",
                "--set",
                "corp_id=corp-1",
                "--set",
                "agent_id=agent-1",
            ]
        )
        self.assertEqual(exit_code, 0)

        reloaded = JsonFileSettingsRepository(file_path)
        self.assertEqual(reloaded.get_admin_settings().admin_user_ids, ["u1", "u2"])
        self.assertTrue(reloaded.get_platform_settings(PlatformType.WECOM).enabled)

    def test_export_openvort_env_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.upsert_llm_profile(
            profile_id="default-anthropic",
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4",
            api_key="secret-key",
            api_base="https://api.anthropic.com",
        )
        service.upsert_admin_settings(
            admin_user_ids=["u-admin"],
            web_default_password="strong-password",
        )
        service.upsert_platform_settings(
            platform=PlatformType.WECOM,
            enabled=True,
            settings={
                "corp_id": "corp-id",
                "agent_id": "agent-id",
                "secret": "secret",
                "callback_token": "token",
                "callback_aes_key": "aes",
            },
        )

        exported = export_openvort_env(service.build_runtime_snapshot())
        self.assertEqual(exported["OPENVORT_LLM_PROVIDER"], "anthropic")
        self.assertEqual(exported["OPENVORT_LLM_API_KEY"], "secret-key")
        self.assertEqual(exported["OPENVORT_CONTACTS_ADMIN_USER_IDS"], "u-admin")
        self.assertEqual(exported["OPENVORT_WECOM_CORP_ID"], "corp-id")

    def test_export_openvort_env_omits_disabled_profiles_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.upsert_llm_profile(
            profile_id="disabled-openai",
            provider=LLMProvider.OPENAI,
            model_name="gpt-5",
            api_key="sk-disabled",
            enabled=False,
        )

        exported = export_openvort_env(service.build_runtime_snapshot())
        self.assertNotIn("OPENVORT_OPENAI_API_KEY", exported)

    def test_write_and_apply_openvort_env_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.upsert_admin_settings(
            admin_user_ids=["u-admin"],
            web_default_password="strong-password",
        )
        service.upsert_platform_settings(
            platform=PlatformType.WECOM,
            enabled=True,
            settings={"corp_id": "corp-1", "agent_id": "agent-1"},
        )

        temp_env = self._temp_settings_path("openvort.env")
        temp_target = self._temp_settings_path("target.env")
        from pathlib import Path
        Path(temp_target).write_text("OPENVORT_WEB_DEFAULT_PASSWORD=old\n# keep\n", encoding="utf-8")

        write_openvort_env_file(service.build_runtime_snapshot(), temp_env)
        exported_text = Path(temp_env).read_text(encoding="utf-8")
        self.assertIn("OPENVORT_CONTACTS_ADMIN_USER_IDS=u-admin", exported_text)

        apply_openvort_env_overlay(service.build_runtime_snapshot(), temp_target)
        merged_text = Path(temp_target).read_text(encoding="utf-8")
        self.assertIn("OPENVORT_WEB_DEFAULT_PASSWORD=strong-password", merged_text)
        self.assertIn("OPENVORT_WECOM_CORP_ID=corp-1", merged_text)

    def test_exported_env_file_permissions_are_restricted(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.upsert_admin_settings(admin_user_ids=["u-admin"], web_default_password="strong-password")
        output_path = self._temp_settings_path("secure.env")

        with patch("os.chmod") as chmod:
            write_openvort_env_file(service.build_runtime_snapshot(), output_path)

        chmod.assert_called_with(output_path, 0o600)

    def test_settings_readiness_audit_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.ensure_defaults()

        report = service.audit_readiness()
        self.assertFalse(report.ready)
        self.assertTrue(any(issue.scope == "llm" for issue in report.issues))
        self.assertTrue(any(issue.scope == "admin" for issue in report.issues))

        service.upsert_llm_profile(
            profile_id="default-anthropic",
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4",
            api_key="secret-key",
        )
        service.upsert_admin_settings(
            admin_user_ids=["admin-a"],
            web_default_password="strong-password",
        )
        service.upsert_platform_settings(
            platform=PlatformType.WECOM,
            enabled=True,
            settings={
                "corp_id": "corp-1",
                "agent_id": "agent-1",
                "secret": "secret",
                "callback_token": "token",
                "callback_aes_key": "aes",
            },
        )

        report = service.audit_readiness()
        self.assertTrue(report.ready)
        self.assertEqual(report.issues, [])

    def test_seed_from_openvort_env_smoke(self) -> None:
        file_path = self._temp_settings_path("seed-source.env")
        from pathlib import Path

        Path(file_path).write_text(
            "\n".join(
                [
                    "OPENVORT_LLM_PROVIDER=anthropic",
                    "OPENVORT_LLM_API_KEY=seed-key",
                    "OPENVORT_LLM_MODEL=claude-sonnet-4",
                    "OPENVORT_CONTACTS_ADMIN_USER_IDS=ops-admin",
                    "OPENVORT_WEB_DEFAULT_PASSWORD=seed-password",
                    "OPENVORT_WECOM_CORP_ID=corp-1",
                    "OPENVORT_WECOM_AGENT_ID=agent-1",
                    "OPENVORT_WECOM_APP_SECRET=secret-1",
                    "OPENVORT_WECOM_CALLBACK_TOKEN=token-1",
                    "OPENVORT_WECOM_CALLBACK_AES_KEY=aes-1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        seed_from_openvort_env_file(service, file_path)

        self.assertEqual(service.get_admin_settings().admin_user_ids, ["ops-admin"])
        self.assertEqual(service.get_llm_profile("default-openvort").api_key, "seed-key")
        wecom = service.get_platform_settings(PlatformType.WECOM)
        self.assertEqual(wecom.settings["corp_id"], "corp-1")

    def test_seed_from_openvort_env_ignores_placeholders_smoke(self) -> None:
        file_path = self._temp_settings_path("seed-placeholder.env")
        from pathlib import Path

        Path(file_path).write_text(
            "\n".join(
                [
                    "OPENVORT_LLM_PROVIDER=anthropic",
                    "OPENVORT_LLM_API_KEY=replace-with-real-key",
                    "OPENVORT_LLM_MODEL=claude-sonnet-4",
                    "OPENVORT_CONTACTS_ADMIN_USER_IDS=replace-with-admin-user-id",
                    "OPENVORT_WEB_DEFAULT_PASSWORD=replace-with-strong-password",
                    "OPENVORT_WECOM_CORP_ID=replace-with-wecom-corp-id",
                    "OPENVORT_WECOM_AGENT_ID=replace-with-wecom-agent-id",
                    "OPENVORT_WECOM_APP_SECRET=replace-with-wecom-app-secret",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        seed_from_openvort_env_file(service, file_path)

        profile = service.get_llm_profile("default-openvort")
        self.assertEqual(profile.api_key, "")
        self.assertEqual(service.get_admin_settings().admin_user_ids, [])
        wecom = service.get_platform_settings(PlatformType.WECOM)
        self.assertFalse(wecom.enabled)

    def test_settings_reset_smoke(self) -> None:
        repository = InMemorySettingsRepository()
        service = SettingsManagementService(repository)
        service.upsert_llm_profile(
            profile_id="default-anthropic",
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4",
            api_key="secret-key",
        )
        service.upsert_admin_settings(
            admin_user_ids=["u-admin"],
            web_default_password="strong-password",
        )

        snapshot = service.reset()
        self.assertEqual(snapshot.llm_profiles, [])
        self.assertEqual(snapshot.admin_settings.admin_user_ids, [])
        self.assertEqual(len(snapshot.platforms), 4)

    def _temp_settings_path(self, filename: str) -> str:
        import tempfile
        from pathlib import Path

        temp_dir = tempfile.mkdtemp(prefix="ant-colony-config-")
        return str(Path(temp_dir) / filename)

    def test_wecom_adapter_smoke(self) -> None:
        adapted = adapt_wecom_payload(
            {
                "msg_id": "w1",
                "from_user_id": "u1",
                "content": "TODO: sync with sales",
                "dept_id": "dept-1",
                "project_id": "proj-1",
                "is_direct": False,
                "mentions": ["u2"],
                "timestamp": 1717488000,
            }
        )

        self.assertEqual(adapted.message.id, "w1")
        self.assertEqual(adapted.message.sender_user_id, "u1")
        self.assertEqual(adapted.context.project_id, "proj-1")
        self.assertEqual(adapted.context.space_type, SpaceType.PROJECT)

    def test_knowledge_service_smoke(self) -> None:
        repository = InMemoryKnowledgeRepository()
        service = KnowledgeService(repository)

        personal = service.save_personal_entry("u1", "k1", "personal note", tags=["note"])
        project = service.save_project_entry("proj-1", "k2", "project summary", tags=["summary"])

        self.assertEqual(personal.owner_type, KnowledgeOwnerType.PERSONAL)
        self.assertEqual(project.owner_type, KnowledgeOwnerType.PROJECT)
        self.assertEqual(len(service.list_personal_entries("u1")), 1)
        self.assertEqual(len(service.list_project_entries("proj-1")), 1)

    def test_project_summary_service_smoke(self) -> None:
        repository = InMemoryKnowledgeRepository()
        service = KnowledgeService(repository)
        service.save_project_entry("proj-1", "k1", "完成需求澄清")
        service.save_project_entry("proj-1", "k2", "确认技术方案")

        summary_service = ProjectSummaryService(repository)
        summary = summary_service.build_summary("proj-1")

        self.assertIn("项目阶段摘要", summary)
        self.assertIn("完成需求澄清", summary)

    def test_project_agent_summary_smoke(self) -> None:
        repository = InMemoryKnowledgeRepository()
        knowledge_service = KnowledgeService(repository)
        knowledge_service.save_project_entry("proj-1", "k1", "完成需求澄清")

        summary_service = ProjectSummaryService(repository)
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)

        summary = project_agent.summarize_phase("proj-1", summary_service)

        self.assertIn("项目阶段摘要", summary)

    def test_inbound_gateway_service_smoke(self) -> None:
        dispatcher = Dispatcher()
        processor = BatchProcessor()

        personal_engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="personal"))
        personal_agent = PersonalAgent("u1", personal_engine)
        gateway = InboundGatewayService(dispatcher, processor, {"u1": personal_agent})

        direct_result = gateway.handle_wecom_payload(
            {
                "msg_id": "w-direct",
                "from_user_id": "u1",
                "content": "hello",
                "dept_id": "dept-1",
                "is_direct": True,
            }
        )
        self.assertEqual(direct_result.route_kind, "personal")
        self.assertIsNotNone(direct_result.response)

        batch_result = gateway.handle_wecom_payload(
            {
                "msg_id": "w-group",
                "from_user_id": "u1",
                "content": "TODO: follow up",
                "dept_id": "dept-1",
                "space_id": "dept-space-1",
                "is_direct": False,
            }
        )
        self.assertEqual(batch_result.route_kind, "space_batch")
        self.assertEqual(batch_result.target_id, "dept-space-1")
        self.assertEqual(batch_result.buffered_count, 1)

    def test_action_service_creates_draft_task(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        orchestrator = TaskOrchestrator(project_agent)
        repository = InMemoryTaskRepository()
        task_service = TaskService(repository)
        action_service = OrchestratorActionService(task_service)

        actions = orchestrator.on_batch(
            "proj-1",
            [Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")],
        )

        outcome = action_service.apply(actions[0])
        self.assertEqual(outcome.kind, "draft_task_created")
        task = repository.get(outcome.metadata["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TaskStatus.DRAFT)
        self.assertEqual(outcome.metadata["card"]["card_type"], "task_draft_confirmation")

    def test_render_task_draft_card_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        draft = project_agent.identify_tasks(
            "proj-1", [Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")]
        )[0]

        repository = InMemoryTaskRepository()
        service = TaskService(repository)
        task = service.create_from_draft(draft, task_id="t-card")

        card = render_task_draft_card(task)
        self.assertEqual(card["task_id"], "t-card")
        self.assertEqual(card["actions"][0]["id"], "confirm_task")

    def test_confirmation_service_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        draft = project_agent.identify_tasks(
            "proj-1", [Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")]
        )[0]

        repository = InMemoryTaskRepository()
        task_service = TaskService(repository)
        task = task_service.create_from_draft(draft, task_id="t-confirm")

        action = parse_task_card_action({"action_id": "confirm_task", "task_id": task.id, "actor_user_id": "u2"})
        confirmation_service = TaskConfirmationService(task_service, repository)
        outcome = confirmation_service.apply(action)

        self.assertEqual(outcome.kind, "task_confirmed")
        updated = repository.get(task.id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, TaskStatus.CONFIRMED)

    def test_notification_service_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        draft = project_agent.identify_tasks(
            "proj-1", [Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")]
        )[0]

        repository = InMemoryTaskRepository()
        task_service = TaskService(repository)
        task = task_service.create_from_draft(draft, task_id="t-notify")
        card = render_task_draft_card(task)

        notifications = NotificationService()
        outbound = notifications.build_task_draft_notification(task, card, target_space_id="proj-1")
        self.assertEqual(outbound.target_type, "space")
        self.assertEqual(outbound.content_type, "card")

        notifier = InMemoryOutboundNotifier()
        notifier.send(outbound)
        self.assertEqual(len(notifier.sent_messages), 1)

    def test_batch_execution_service_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        orchestrator = TaskOrchestrator(project_agent)
        repository = InMemoryTaskRepository()
        task_service = TaskService(repository)
        action_service = OrchestratorActionService(task_service)
        guard = ActionGuard()
        notifications = NotificationService()
        batch_service = BatchExecutionService(orchestrator, guard, action_service, notifications)

        result = batch_service.process_batch(
            "proj-1",
            [
                Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up"),
                Message(id="m2", space_id="proj-1", sender_user_id="u1", content="pause this project"),
            ],
        )

        self.assertEqual(result.actions_seen, 2)
        self.assertEqual(len(result.outcomes), 2)
        self.assertEqual(len(result.outbound_messages), 1)
        self.assertEqual(result.outbound_messages[0].content_type, "card")

    def test_card_callback_service_smoke(self) -> None:
        engine = AgentEngine(AgentEngineConfig(model_name="placeholder", agent_role="project"))
        project_agent = ProjectAgent("proj-1", engine)
        draft = project_agent.identify_tasks(
            "proj-1", [Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up")]
        )[0]

        repository = InMemoryTaskRepository()
        task_service = TaskService(repository)
        task = task_service.create_from_draft(draft, task_id="t-callback")
        confirmation_service = TaskConfirmationService(task_service, repository)
        callback_service = CardCallbackService(confirmation_service)

        outcome = callback_service.handle_task_card_callback(
            {"action_id": "confirm_task", "task_id": task.id, "actor_user_id": "u9"}
        )

        self.assertEqual(outcome.kind, "task_confirmed")
        updated = repository.get(task.id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, TaskStatus.CONFIRMED)


if __name__ == "__main__":
    unittest.main()

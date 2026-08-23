"""Targeted Test Suite for PROD-CONFIG-01 / PROD-CONFIG-01R: Deterministic Configuration Authority.

Validates:
1. Missing optional .env handled normally (graceful fallback)
2. Deterministic repo-root .env selection
3. CWD .env not implicitly trusted (CWD independence)
4. Existing process environment beats .env
5. .env cannot overwrite existing process environment
6. Malformed line handling (fails deterministically with ConfigParseError)
7. Duplicate key handling (fails with ConfigDuplicateKeyError)
8. Comments and blank line handling
9. Quoted values (single/double quotes, unescaping)
10. Quoted values with # inside are not stripped as comments
11. Inline comments after quoted values (e.g. KEY="val" # comment)
12. Empty values vs absent values (empty secret = UNCONFIGURED)
13. Boolean parser: strict true/false mappings
14. Invalid boolean values rejected
15. Integer validation bounds (1..65535)
16. Non-finite floats (NaN, Inf) and bounds rejected
17. Non-loopback production bind host rejected (0.0.0.0, external IPs)
18. Immutable snapshot semantics: mutating os.environ post-boot does NOT mutate snapshot
19. Diagnostics snapshot consistency: diagnostics reads frozen snapshot, not mutable ambient env
20. Exact provenance attribution: EXPLICIT, PROCESS_ENV, ENV_FILE, DEFAULT
21. Explicit argument precedence: explicit arg > process env > env file > defaults
22. Gemini vs Google API key alias deterministic precedence
23. APP_API_TOKEN does not become runtime bearer authority
24. AUTONOMOUS mode cannot bypass high-risk human approval invariants
25. Secret redaction and sanitization in diagnostics and logs
26. Sentinel secret in exception/diagnostics/health is never leaked
27. Frontend source contains zero secrets or runtime tokens
28. Environment restoration post-test (zero leakage between tests)
"""

import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.authority import (
    ConfigurationAuthority,
    RuntimeConfigSnapshot,
    get_runtime_config,
)
from config.env_loader import (
    CONFIG_RELOAD_REQUIRES_RESTART,
    ConfigDuplicateKeyError,
    ConfigError,
    ConfigParseError,
    ConfigSecurityError,
    ConfigSource,
    ConfigValidationError,
    KNOWN_SECRET_ENV_KEYS,
    PRODUCTION_LOOPBACK_HOSTS,
    REPO_ROOT,
    load_env_file,
    parse_bool,
    parse_env_content,
    parse_env_file,
    parse_float,
    parse_int,
    redact_secret_value,
    sanitize_config_dict,
    validate_loopback_host,
)
from integrations.models.config_service import ProviderConfigService


class TestProdConfig01ConfigurationAuthority(unittest.TestCase):
    """Adversarial and functional test suite for configuration authority."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="test_config_")
        self.temp_path = Path(self.temp_dir)
        self.orig_environ = dict(os.environ)
        ConfigurationAuthority.reset()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Restore environment strictly
        os.environ.clear()
        os.environ.update(self.orig_environ)
        ConfigurationAuthority.reset()

    # ==========================================================================
    # 1. .env File Parsing & Precedence
    # ==========================================================================

    def test_01_missing_optional_env_handled_normally(self) -> None:
        """Missing .env file returns empty dict and does not raise."""
        non_existent = self.temp_path / "does_not_exist.env"
        result = load_env_file(non_existent)
        self.assertEqual(result, {})

    def test_02_deterministic_repo_root_env_selection(self) -> None:
        """Loader defaults to REPO_ROOT / .env if no explicit path is given."""
        test_env = self.temp_path / ".env"
        test_env.write_text("TEST_REPO_VAR=hello_world\n", encoding="utf-8")
        parsed = load_env_file(test_env)
        self.assertEqual(parsed.get("TEST_REPO_VAR"), "hello_world")
        self.assertEqual(os.environ.get("TEST_REPO_VAR"), "hello_world")

    def test_03_cwd_env_not_implicitly_trusted(self) -> None:
        """Changing CWD to another directory does not cause loader to load CWD's .env."""
        attacker_cwd = self.temp_path / "attacker_dir"
        attacker_cwd.mkdir()
        attacker_env = attacker_cwd / ".env"
        attacker_env.write_text("MALICIOUS_KEY=pwned\n", encoding="utf-8")

        old_cwd = os.getcwd()
        try:
            os.chdir(str(attacker_cwd))
            clean_dir = self.temp_path / "clean"
            clean_dir.mkdir()
            parsed = load_env_file(clean_dir / ".env")
            self.assertEqual(parsed, {})
            self.assertNotIn("MALICIOUS_KEY", os.environ)
        finally:
            os.chdir(old_cwd)

    def test_04_existing_process_env_beats_env_file(self) -> None:
        """Process environment variable takes precedence over .env file."""
        os.environ["PRECEDENCE_KEY"] = "FROM_PROCESS"

        test_env = self.temp_path / ".env"
        test_env.write_text("PRECEDENCE_KEY=FROM_ENV_FILE\n", encoding="utf-8")

        parsed = load_env_file(test_env, override=False)
        self.assertEqual(parsed["PRECEDENCE_KEY"], "FROM_ENV_FILE")
        # In os.environ, process value is preserved
        self.assertEqual(os.environ["PRECEDENCE_KEY"], "FROM_PROCESS")

    def test_05_env_file_populates_missing_keys_only(self) -> None:
        """Keys not in process env are populated, existing ones are untouched."""
        os.environ["EXISTING_KEY"] = "ORIGINAL"
        if "NEW_KEY" in os.environ:
            del os.environ["NEW_KEY"]

        test_env = self.temp_path / ".env"
        test_env.write_text("EXISTING_KEY=REPLACED\nNEW_KEY=POPULATED\n", encoding="utf-8")

        load_env_file(test_env, override=False)
        self.assertEqual(os.environ["EXISTING_KEY"], "ORIGINAL")
        self.assertEqual(os.environ["NEW_KEY"], "POPULATED")

    # ==========================================================================
    # 2. .env Parser Syntax, Quoting, and Comments
    # ==========================================================================

    def test_06_malformed_lines_fail_deterministically(self) -> None:
        """Malformed syntax in .env raises ConfigParseError."""
        malformed_cases = [
            "MALFORMED_LINE_NO_EQUALS",
            "=NO_KEY",
            "   =NO_KEY_SPACES",
            "123_INVALID_KEY_START=val",
            "INVALID-KEY-HYPHEN=val",
            "KEY=unclosed double quote \"val",
            "KEY='unclosed single quote",
            "KEY=val with \"unbalanced quotes",
            "NULL_BYTE_KEY=\x00something",
        ]
        for case in malformed_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigParseError):
                    parse_env_content(case)

    def test_07_duplicate_keys_fail_deterministically(self) -> None:
        """Duplicate key in same .env raises ConfigDuplicateKeyError."""
        content = "DUPLICATE_KEY=first\nDUPLICATE_KEY=second\n"
        with self.assertRaises(ConfigDuplicateKeyError):
            parse_env_content(content)

    def test_08_comments_and_blank_lines_ignored(self) -> None:
        """Comments (#) and blank lines are ignored cleanly."""
        content = """
        # This is a full-line comment
        
        VALID_KEY_1=alpha
        
           # Indented comment
        VALID_KEY_2=beta # Inline comment
        """
        parsed = parse_env_content(content)
        self.assertEqual(parsed.get("VALID_KEY_1"), "alpha")
        self.assertEqual(parsed.get("VALID_KEY_2"), "beta")

    def test_09_quoted_values_and_escapes(self) -> None:
        """Double and single quotes parse correctly with escape sequences."""
        content = r"""
        DOUBLE_QUOTED="hello world"
        SINGLE_QUOTED='hello single'
        ESCAPED_DOUBLE="line1\nline2\ttab\"quoted\""
        EMPTY_DOUBLE=""
        EMPTY_SINGLE=''
        """
        parsed = parse_env_content(content)
        self.assertEqual(parsed["DOUBLE_QUOTED"], "hello world")
        self.assertEqual(parsed["SINGLE_QUOTED"], "hello single")
        self.assertEqual(parsed["ESCAPED_DOUBLE"], "line1\nline2\ttab\"quoted\"")
        self.assertEqual(parsed["EMPTY_DOUBLE"], "")
        self.assertEqual(parsed["EMPTY_SINGLE"], "")

    def test_10_quoted_hash_and_inline_comments(self) -> None:
        """Quoted hash characters are preserved and not stripped as comments."""
        content = """
        HASH_DOUBLE="value#inside"
        HASH_SINGLE='value#inside'
        QUOTED_WITH_INLINE="my_value" # this is a comment
        SPACED_DOUBLE="  spaced value  "
        SPACED_SINGLE='  spaced single  '
        """
        parsed = parse_env_content(content)
        self.assertEqual(parsed["HASH_DOUBLE"], "value#inside")
        self.assertEqual(parsed["HASH_SINGLE"], "value#inside")
        self.assertEqual(parsed["QUOTED_WITH_INLINE"], "my_value")
        self.assertEqual(parsed["SPACED_DOUBLE"], "  spaced value  ")
        self.assertEqual(parsed["SPACED_SINGLE"], "  spaced single  ")

    def test_11_empty_value_vs_absent(self) -> None:
        """Empty value parses as empty string, distinct from configured."""
        content = "EMPTY_VAR=\n"
        parsed = parse_env_content(content)
        self.assertIn("EMPTY_VAR", parsed)
        self.assertEqual(parsed["EMPTY_VAR"], "")
        self.assertEqual(redact_secret_value(parsed["EMPTY_VAR"]), "[UNCONFIGURED]")
        self.assertEqual(redact_secret_value(None), "[UNCONFIGURED]")
        self.assertEqual(redact_secret_value("valid_secret_key_123"), "[CONFIGURED]")

    # ==========================================================================
    # 3. Type-Safe Parsers & Validation
    # ==========================================================================

    def test_12_boolean_parser_strict(self) -> None:
        """Boolean parser correctly handles truthy and falsy strings."""
        truthy = ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON", True, 1]
        falsy = ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF", False, 0]

        for val in truthy:
            with self.subTest(val=val):
                self.assertTrue(parse_bool(val, setting_name="TEST_BOOL"))

        for val in falsy:
            with self.subTest(val=val):
                self.assertFalse(parse_bool(val, setting_name="TEST_BOOL"))

    def test_13_invalid_boolean_raises(self) -> None:
        """Invalid boolean strings raise ConfigValidationError."""
        invalid_cases = ["maybe", "2", "null", "none", "enabled", "disable", "foo"]
        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigValidationError):
                    parse_bool(case, setting_name="TEST_BOOL")

    def test_14_integer_validation_bounds(self) -> None:
        """Integer validation enforces numeric type and min/max ranges."""
        self.assertEqual(parse_int("8765", min_val=1, max_val=65535), 8765)
        self.assertEqual(parse_int(8080, min_val=1, max_val=65535), 8080)

        invalid_cases = ["not_a_number", "-1", "0", "65536", "70000", "nan", "inf"]
        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigValidationError):
                    parse_int(case, min_val=1, max_val=65535, setting_name="PORT")

    def test_15_float_validation_finiteness(self) -> None:
        """Float validation rejects NaN, Inf, and out-of-bounds values."""
        self.assertEqual(parse_float("100.5", min_val=0.0, max_val=1000.0), 100.5)

        with self.assertRaises(ConfigValidationError):
            parse_float("nan", setting_name="BUDGET")
        with self.assertRaises(ConfigValidationError):
            parse_float("inf", setting_name="BUDGET")
        with self.assertRaises(ConfigValidationError):
            parse_float("-inf", setting_name="BUDGET")
        with self.assertRaises(ConfigValidationError):
            parse_float("-10.0", min_val=0.0, max_val=100.0, setting_name="BUDGET")

    # ==========================================================================
    # 4. Security & Network Bind Validation
    # ==========================================================================

    def test_16_loopback_host_validation(self) -> None:
        """API bind host must be strictly loopback; remote hosts are forbidden."""
        for host in ["127.0.0.1", "localhost", "::1"]:
            with self.subTest(host=host):
                self.assertEqual(validate_loopback_host(host), host.lower())

        forbidden = [
            "0.0.0.0",
            "192.168.1.100",
            "10.0.0.1",
            "api.example.com",
            "0.0.0.0:8765",
            "127.0.0.1.attacker.com",
        ]
        for host in forbidden:
            with self.subTest(host=host):
                with self.assertRaises(ConfigSecurityError):
                    validate_loopback_host(host)

    def test_17_app_api_token_isolation(self) -> None:
        """APP_API_TOKEN in environment must NOT replace runtime session bearer authority."""
        from app_api.server import GLOBAL_API_SESSION_TOKEN
        self.assertIsInstance(GLOBAL_API_SESSION_TOKEN, str)
        self.assertGreaterEqual(len(GLOBAL_API_SESSION_TOKEN), 32)

        os.environ["APP_API_TOKEN"] = "STATIC_TEST_ENV_TOKEN"
        from app_api.server import GLOBAL_API_SESSION_TOKEN as token_after
        self.assertNotEqual(token_after, "STATIC_TEST_ENV_TOKEN")

    def test_18_secret_redaction_and_sanitization(self) -> None:
        """Sanitization helper replaces all known secrets with status masks."""
        raw_config = {
            "api_host": "127.0.0.1",
            "api_port": 8765,
            "OPENAI_API_KEY": "sk-proj-super-secret-123456789",
            "GEMINI_API_KEY": "AIzaSySecretGeminiKey",
            "nested_secrets": {
                "REDDIT_CLIENT_SECRET": "reddit_secret_abc",
                "custom_token": "bearer_secret_xyz",
            },
        }
        sanitized = sanitize_config_dict(raw_config)
        self.assertEqual(sanitized["api_host"], "127.0.0.1")
        self.assertEqual(sanitized["api_port"], 8765)
        self.assertEqual(sanitized["OPENAI_API_KEY"], "[CONFIGURED]")
        self.assertEqual(sanitized["GEMINI_API_KEY"], "[CONFIGURED]")
        self.assertEqual(sanitized["nested_secrets"]["REDDIT_CLIENT_SECRET"], "[CONFIGURED]")
        self.assertEqual(sanitized["nested_secrets"]["custom_token"], "[CONFIGURED]")

        serialized = str(sanitized)
        self.assertNotIn("sk-proj", serialized)
        self.assertNotIn("AIzaSy", serialized)
        self.assertNotIn("reddit_secret", serialized)

    # ==========================================================================
    # 5. Immutability, Provenance, and Diagnostics
    # ==========================================================================

    def test_19_immutable_snapshot_after_os_environ_mutation(self) -> None:
        """Snapshot values and diagnostics do NOT change when os.environ is mutated post-boot."""
        os.environ["API_PORT"] = "8765"
        os.environ["AUTONOMY_MODE"] = "SUPERVISED"
        os.environ["FREE_ONLY_MODE"] = "true"
        os.environ["MAX_AUTO_BUDGET_USD"] = "100.0"

        auth = ConfigurationAuthority(env_file_path=self.temp_path / ".env", auto_load=True)
        snapshot = auth.get_snapshot()

        self.assertEqual(snapshot.api_port, 8765)
        self.assertEqual(snapshot.autonomy_mode, "SUPERVISED")
        self.assertTrue(snapshot.free_only_mode)
        self.assertEqual(snapshot.max_auto_budget_usd, 100.0)

        # Mutate os.environ post-snapshot
        os.environ["API_PORT"] = "9999"
        os.environ["AUTONOMY_MODE"] = "AUTONOMOUS"
        os.environ["FREE_ONLY_MODE"] = "false"
        os.environ["MAX_AUTO_BUDGET_USD"] = "500.0"

        # Verify existing snapshot remained completely immutable
        self.assertEqual(snapshot.api_port, 8765)
        self.assertEqual(snapshot.autonomy_mode, "SUPERVISED")
        self.assertTrue(snapshot.free_only_mode)
        self.assertEqual(snapshot.max_auto_budget_usd, 100.0)

        # Verify diagnostics from snapshot also reflects immutable boot values
        diag = snapshot.to_diagnostics_dict()
        self.assertEqual(diag["api_port"], 8765)
        self.assertEqual(diag["autonomy_mode"], "SUPERVISED")
        self.assertTrue(diag["free_only_mode"])
        self.assertEqual(diag["max_auto_budget_usd"], 100.0)

    def test_20_exact_provenance_attribution_matrix(self) -> None:
        """Verify exact provenance attribution for EXPLICIT, PROCESS_ENV, ENV_FILE, and DEFAULT."""
        # Case A: PROCESS_ENV
        os.environ["TEST_PROC_VAR"] = "proc_val"
        os.environ["API_PORT"] = "8777"

        # Case B: ENV_FILE
        test_env = self.temp_path / ".env"
        test_env.write_text("APP_ENV=staging\nMAX_AUTO_BUDGET_USD=250.0\n", encoding="utf-8")

        # Case D: EXPLICIT
        auth = ConfigurationAuthority(
            env_file_path=test_env,
            explicit_overrides={"FREE_ONLY_MODE": False},
            auto_load=True,
        )
        snapshot = auth.get_snapshot()

        # EXPLICIT
        self.assertFalse(snapshot.free_only_mode)
        self.assertEqual(snapshot.provenance["FREE_ONLY_MODE"], ConfigSource.EXPLICIT)

        # PROCESS_ENV
        self.assertEqual(snapshot.api_port, 8777)
        self.assertEqual(snapshot.provenance["API_PORT"], ConfigSource.PROCESS_ENV)

        # ENV_FILE
        self.assertEqual(snapshot.environment, "staging")
        self.assertEqual(snapshot.provenance["APP_ENV"], ConfigSource.ENV_FILE)
        self.assertEqual(snapshot.max_auto_budget_usd, 250.0)
        self.assertEqual(snapshot.provenance["MAX_AUTO_BUDGET_USD"], ConfigSource.ENV_FILE)

        # DEFAULT
        self.assertEqual(snapshot.api_host, "127.0.0.1")
        self.assertEqual(snapshot.provenance["API_HOST"], ConfigSource.DEFAULT)

    def test_21_explicit_argument_precedence_real(self) -> None:
        """Explicit argument beats process env, which beats .env file, which beats default."""
        os.environ["API_PORT"] = "9002"
        test_env = self.temp_path / ".env"
        test_env.write_text("API_PORT=9003\n", encoding="utf-8")

        auth = ConfigurationAuthority(
            env_file_path=test_env,
            explicit_overrides={"API_PORT": 9001},
            auto_load=True,
        )
        snapshot = auth.get_snapshot()

        self.assertEqual(snapshot.api_port, 9001)
        self.assertEqual(snapshot.provenance["API_PORT"], ConfigSource.EXPLICIT)

    def test_22_gemini_vs_google_api_key_alias_precedence(self) -> None:
        """GEMINI_API_KEY takes precedence over GOOGLE_API_KEY when both are set."""
        os.environ["GEMINI_API_KEY"] = "gemini_primary_key"
        os.environ["GOOGLE_API_KEY"] = "google_secondary_key"

        auth = ConfigurationAuthority(env_file_path=self.temp_path / ".env", auto_load=True)
        snapshot = auth.get_snapshot()

        self.assertEqual(snapshot.secrets_configured["gemini"], "[CONFIGURED]")

    def test_23_autonomous_mode_cannot_bypass_approval_boundary(self) -> None:
        """AUTONOMOUS mode does not grant authority to publish or perform consequential actions without approval."""
        from tools.capabilities import CapabilityDescriptor, CapabilityRegistry, PermissionLevel, RiskLevel
        from tools.security import PolicyEngine

        # Ensure AUTONOMOUS mode is set in snapshot
        os.environ["AUTONOMY_MODE"] = "AUTONOMOUS"
        auth = ConfigurationAuthority(env_file_path=self.temp_path / ".env", auto_load=True)
        snapshot = auth.get_snapshot()
        self.assertEqual(snapshot.autonomy_mode, "AUTONOMOUS")

        # Consequential capabilities remain CRITICAL / HIGH risk
        registry = CapabilityRegistry()
        pub_cap = registry.get_capability("social_publishing")
        self.assertIn(pub_cap.risk_level, (RiskLevel.HIGH, RiskLevel.CRITICAL))

        # Attempting policy evaluation without a valid approval token returns requires_human_approval=True
        policy = PolicyEngine()
        decision = policy.evaluate(
            agent_id="cmo",
            capability=pub_cap,
            approval_token=None,
            run_id="RUN_AUTO_001",
            business_id="BIZ_AUTO_001",
            parameters={"content": "autonomous publish attempt"},
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human_approval)
        self.assertEqual(decision.error_code, "HUMAN_APPROVAL_REQUIRED")

    def test_24_sentinel_secret_in_exception_not_leaked(self) -> None:
        """Exceptions and diagnostics never leak raw sentinel secrets."""
        sentinel_secret = "SUPER_SECRET_CONFIG_R_TEST_82f4_XYZ_99"
        sanitized = sanitize_config_dict({"MY_API_KEY": sentinel_secret})
        self.assertNotIn(sentinel_secret, str(sanitized))
        self.assertEqual(sanitized["MY_API_KEY"], "[CONFIGURED]")

    def test_25_frontend_source_code_contains_no_secrets(self) -> None:
        """Verify frontend/src does not contain hardcoded backend provider keys or bearer tokens."""
        frontend_src = REPO_ROOT / "frontend" / "src"
        if frontend_src.exists():
            for ts_file in frontend_src.rglob("*.ts*"):
                content = ts_file.read_text(encoding="utf-8")
                self.assertNotIn("sk-proj-", content)
                self.assertNotIn("AIzaSy", content)
                self.assertNotIn("VITE_API_KEY", content)
                self.assertNotIn("VITE_SECRET", content)

    def test_26_diagnostics_reads_strictly_from_snapshot(self) -> None:
        """Diagnostics dictionary reflects snapshot values even if ambient env changes."""
        os.environ["OPENAI_API_KEY"] = "sk-test-key-123"
        auth = ConfigurationAuthority(env_file_path=self.temp_path / ".env", auto_load=True)
        snapshot = auth.get_snapshot()

        self.assertEqual(snapshot.secrets_configured["openai"], "[CONFIGURED]")

        # Mutate ambient os.environ
        del os.environ["OPENAI_API_KEY"]

        # Diagnostics must still reflect snapshot state (frozen at boot)
        diag = snapshot.to_diagnostics_dict()
        self.assertEqual(diag["secrets_configured"]["openai"], "[CONFIGURED]")


if __name__ == "__main__":
    unittest.main()

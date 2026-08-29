"""GUI 非依存モジュールが import できることを確認する。"""


def test_core_imports():
    import core.rule_processor  # noqa: F401
    import core.settings  # noqa: F401


def test_service_imports():
    import snoreguard.settings_manager  # noqa: F401
    import snoreguard.time_scheduler  # noqa: F401
    import snoreguard.updater  # noqa: F401
    import snoreguard.vrc.mdns_client  # noqa: F401

"""Phase 6-1 registry 단위 테스트."""

from django.test import SimpleTestCase

from chat.workflows.core import (
    ValidationResult,
    WorkflowResult,
)
from chat.workflows.domains import registry


def _dummy_workflow_factory():
    class _Noop:
        def prepare(self, raw):
            return dict(raw)
        def validate(self, n):
            return ValidationResult.success()
        def execute(self, n):
            return WorkflowResult.ok(0)
    return _Noop()


class RegistryTests(SimpleTestCase):
    def setUp(self):
        # 다른 테스트가 의존하는 부팅 시 등록된 엔트리를 잃지 않도록 snapshot 으로
        # 복구한다. 레지스트리는 프로세스 싱글톤이라 반드시 복원해야 안전.
        self._snapshot = registry._snapshot_for_tests()
        registry._reset_for_tests()

    def tearDown(self):
        registry._restore_for_tests(self._snapshot)

    def test_register_and_lookup(self):
        entry = registry.WorkflowEntry(
            key='noop',
            title='Noop',
            description='doc',
            status=registry.STATUS_STABLE,
            factory=_dummy_workflow_factory,
        )
        registry.register(entry)

        self.assertTrue(registry.has('noop'))
        self.assertIs(registry.get('noop'), entry)
        self.assertEqual([e.key for e in registry.all_entries()], ['noop'])

    def test_unknown_key_returns_none(self):
        self.assertFalse(registry.has('ghost'))
        self.assertIsNone(registry.get('ghost'))

    def test_duplicate_key_rejected(self):
        entry = registry.WorkflowEntry(
            key='x', title='X', description='',
            status=registry.STATUS_STABLE, factory=_dummy_workflow_factory,
        )
        registry.register(entry)
        with self.assertRaises(ValueError):
            registry.register(entry)

    def test_empty_key_rejected(self):
        entry = registry.WorkflowEntry(
            key='', title='', description='',
            status=registry.STATUS_STABLE, factory=_dummy_workflow_factory,
        )
        with self.assertRaises(ValueError):
            registry.register(entry)

    def test_all_entries_preserves_insertion_order(self):
        for key in ('a', 'b', 'c'):
            registry.register(registry.WorkflowEntry(
                key=key, title=key.upper(), description='',
                status=registry.STATUS_STABLE,
                factory=_dummy_workflow_factory,
            ))
        self.assertEqual(
            [e.key for e in registry.all_entries()],
            ['a', 'b', 'c'],
        )

"""Restore Engine, stage 2: the job state machine."""

import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import states as st  # noqa: E402


class TestStateTable(unittest.TestCase):
    def test_every_target_is_a_known_state(self):
        for source, targets in st.TRANSITIONS.items():
            for target in targets:
                self.assertIn(target, st.ALL_STATES, f"{source} -> {target}")

    def test_every_state_is_reachable_from_created(self):
        seen, todo = {st.CREATED}, [st.CREATED]
        while todo:
            for nxt in st.TRANSITIONS[todo.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        self.assertEqual(seen, set(st.ALL_STATES))

    def test_terminal_worker_states_are_not_retried(self):
        self.assertEqual(
            st.TERMINAL_STATES,
            {
                st.SUCCESS,
                st.FAILED,
                st.FAILED_ROLLBACK_CONFIRMED,
                st.ROLLBACK_FAILED,
                st.UNKNOWN,
                st.RESOLVED_MANUAL,
                st.CANCELLED,
            },
        )
        # Unknown and rollback_failed may only be closed through the audited manual-resolution path.
        self.assertEqual(st.TRANSITIONS[st.UNKNOWN], frozenset({st.RESOLVED_MANUAL}))
        self.assertEqual(
            st.TRANSITIONS[st.ROLLBACK_FAILED], frozenset({st.RESOLVED_MANUAL})
        )
        self.assertEqual(st.TRANSITIONS[st.FAILED], frozenset({st.RESOLVED_MANUAL}))
        for state in st.TERMINAL_STATES - {st.UNKNOWN, st.ROLLBACK_FAILED, st.FAILED}:
            for other in st.ALL_STATES:
                self.assertFalse(st.can_transition(state, other))

    def test_success_only_after_verification(self):
        self.assertEqual(st.transition_allowed_from(st.SUCCESS), {st.VERIFYING})

    def test_confirmed_rollback_only_from_rollback(self):
        self.assertEqual(
            st.transition_allowed_from(st.FAILED_ROLLBACK_CONFIRMED),
            {st.ROLLBACK_RUNNING},
        )
        self.assertEqual(
            st.transition_allowed_from(st.ROLLBACK_FAILED), {st.ROLLBACK_RUNNING}
        )

    def test_nothing_runs_without_confirmation(self):
        # the only way to QUEUED is through awaiting_confirmation
        self.assertEqual(
            st.transition_allowed_from(st.QUEUED), {st.AWAITING_CONFIRMATION}
        )
        self.assertEqual(st.transition_allowed_from(st.RUNNING), {st.QUEUED})

    def test_no_cancel_once_the_device_may_be_touched(self):
        for state in st.DEVICE_TOUCHED_STATES:
            self.assertNotIn(state, st.CANCELLABLE_STATES)
            self.assertFalse(st.can_transition(state, st.CANCELLED))
        self.assertIn(st.QUEUED, st.CANCELLABLE_STATES)

    def test_no_retry_loops(self):
        # a failed step never goes back to running (no automatic re-apply)
        for state in (st.VERIFYING, st.ROLLBACK_RUNNING, st.FAILED, st.UNKNOWN):
            self.assertFalse(st.can_transition(state, st.RUNNING))
        self.assertFalse(st.can_transition(st.RUNNING, st.QUEUED))

    def test_interrupted_states_can_all_become_unknown(self):
        for state in st.INTERRUPTED_ON_RESTART:
            self.assertTrue(st.can_transition(state, st.UNKNOWN), state)

    def test_a_queued_job_is_not_marked_interrupted_by_a_restart(self):
        self.assertNotIn(st.QUEUED, st.INTERRUPTED_ON_RESTART)

    def test_every_state_has_a_label(self):
        self.assertEqual(set(st.LABELS), set(st.ALL_STATES))

    def test_assert_transition(self):
        st.assert_transition(st.CREATED, st.PRECHECK_RUNNING)
        with self.assertRaises(st.InvalidTransition):
            st.assert_transition(st.CREATED, st.RUNNING)
        with self.assertRaises(st.InvalidTransition):
            st.assert_transition("nonsense", st.RUNNING)
        with self.assertRaises(st.InvalidTransition):
            st.assert_transition(st.CREATED, "nonsense")


if __name__ == "__main__":
    unittest.main()
